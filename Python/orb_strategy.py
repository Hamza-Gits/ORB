"""
orb_strategy.py
===============
Core engine for the 5-minute Opening Range Breakout (ORB) backtest.

This module is the single source of truth for the trading logic. Both
`orb_backtest.py` (one run) and `orb_optimize.py` (grid search) import it.

It mirrors the NinjaScript strategy `FiveMinuteORB.cs`:
    - mark the High/Low of the first N minutes after the open  -> Opening Range
    - go LONG  on a break of the OR high (stop = OR low)
    - go SHORT on a break of the OR low  (stop = OR high)
    - target  = Reward:Risk * (range)
    - one trade/day by default, flatten by `exit_time`.

Nothing here looks into the future: entries are decided from each bar's own
high/low, and when a single bar could have hit both stop and target we resolve
it pessimistically (assume the stop filled first). That keeps the backtest
honest rather than flattering.

Audit fixes (2026-06-22)
------------------------
LA1  - Gap-through: guard hit_tgt so target can never be "behind" the fill.
LA2  - R-multiple now uses realized fill-to-stop risk, not planned trigger-to-stop.
LA3  - profit_factor returns nan (not inf) when no losses; scratch trades excluded
       from the loss bucket so they don't inflate PF.
EX1  - Trade window is now inclusive="left" so the last accepted bar is the one
       whose start-stamp is strictly before exit_time, matching NT's close-stamp
       >= ExitTime check (prevents 1-2 extra bars near the flatten boundary).
DST  - ambiguous="infer" instead of "NaT" prevents silent data loss during the
       US fall-back hour for 24h futures CSVs.
HDR  - Header autodetection strengthened: also detects abbreviated OHLC headers
       (o,h,l,c) where no cell matches the keyword list.
SEP  - Delimiter autodetection now uses csv.Sniffer over the first 4 KB.
DEDUP- Source dedup applied before DST localisation; post-transform collisions
       warn instead of silently discarding data.
AMB1 - NOTE (documented, not fully fixable without tick data): when a single bar
       engulfs both the long trigger and the short trigger, Python picks the side
       whose trigger is nearer to the bar's open. NinjaTrader fills whichever
       stop-market executes first per its intrabar fill engine. These can differ
       on straddle bars; treat the Python result as an approximation.
"""

import csv
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Instrument specifications (CME index futures)
#   point_value = tick_value / tick_size
#       MNQ -> $2.00 / point      MES -> $5.00 / point
#       NQ  -> $20.00 / point     ES  -> $50.00 / point
# ---------------------------------------------------------------------------
INSTRUMENTS = {
    "MNQ": {"tick_size": 0.25, "tick_value": 0.50},   # Micro E-mini Nasdaq-100
    "MES": {"tick_size": 0.25, "tick_value": 1.25},   # Micro E-mini S&P 500
    "NQ":  {"tick_size": 0.25, "tick_value": 5.00},   # E-mini Nasdaq-100
    "ES":  {"tick_size": 0.25, "tick_value": 12.50},  # E-mini S&P 500
}


@dataclass
class Params:
    """All knobs for one backtest run. The optimizer just sweeps these."""
    instrument: str = "MNQ"
    or_start: str = "09:30"      # opening-range start (exchange/ET time)
    or_minutes: int = 5          # opening-range length
    exit_time: str = "15:55"     # force-flat time (bars with start-stamp >= this are excluded)
    rr: float = 1.0              # reward:risk (1.0, 1.5, 2.0 ...)
    offset_ticks: int = 0        # extra ticks beyond the level to trigger entry
    direction: str = "both"      # "both" | "long" | "short"
    max_trades: int = 1          # trades per day
    contracts: int = 1
    commission_rt: float = 1.24  # commission per contract, round-turn ($)
    slippage_ticks: int = 1      # slippage applied to stop fills (entry + stop-loss)
    pessimistic: bool = True     # same-bar stop+target -> assume stop filled first
    # Volatility filter on the opening-range WIDTH (in index points). Not lookahead:
    # the OR width is known the instant the OR closes, before any entry is taken.
    min_or_points: float = 0.0   # skip the day if OR width < this (0 = off)
    max_or_points: float = 0.0   # skip the day if OR width > this (0 = off; filters choppy days)
    # Directional bias / trend filter. When active, only the trend-side breakout is
    # taken each day (decided at OR close -> no lookahead):
    #   "ema_slope"  daily-close EMA rising -> longs only, falling -> shorts only
    #   "ema_price"  OR-close price above daily EMA -> longs, below -> shorts
    #   "vwap"       OR-close price above intraday VWAP -> longs, below -> shorts
    #   "vwap_slope" intraday VWAP rising across the OR -> longs, falling -> shorts
    #   "none"       no bias (default)
    bias: str = "none"
    ema_period: int = 20          # daily-close EMA period for the ema biases
    bias_slope_lookback: int = 1  # days, slope window for ema_slope
    # Entry style. "stop" = enter on the first TOUCH of the level (default). The
    # others wait for confirmation to dodge wick / false breakouts (see _find_entry):
    #   "close"   enter only when a bar CLOSES beyond the level
    #   "rebreak" break -> a bar closes back INSIDE -> break again, then enter
    #   "retest"  break (close beyond) -> pull back to the level, then enter there
    entry_mode: str = "stop"
    # --- Tier-1 risk & durability variables (all default to the OR baseline) ---
    stop_mode: str = "or"        # "or"=opposite OR extreme (default) | "points" | "atr" | "or_frac"
    stop_points: float = 0.0     # fixed stop distance in points (stop_mode="points")
    stop_atr_mult: float = 1.0   # daily-ATR multiple for the stop (stop_mode="atr")
    stop_or_frac: float = 1.0    # fraction of the OR width for the stop (stop_mode="or_frac")
    atr_period: int = 14         # daily ATR period
    risk_dollars: float = 0.0    # >0 -> size contracts to ~constant $ risk per trade
    max_contracts: int = 10      # cap when sizing by risk_dollars
    regime: str = "none"         # "none" | "adx" | "ma" -- only trade in a trending regime
    regime_adx_min: float = 20.0  # min daily ADX to trade (regime="adx")
    regime_ma_period: int = 50   # SMA period for regime="ma"
    entry_cutoff: str = ""       # no NEW entries at/after this time ("" = off)
    skip_nfp: bool = False       # skip first-Friday (jobs-report) days
    skip_opex: bool = False      # skip third-Friday (options-expiry) days
    # --- Tier-2 exit-management variables (default OFF -> baseline unchanged) ---
    breakeven_r: float = 0.0     # move stop to entry once price reaches this R (0=off)
    trail_mode: str = "none"     # "none" | "ticks" | "atr"  (trailing stop)
    trail_ticks: float = 0.0     # trail distance in ticks (trail_mode="ticks")
    trail_atr_mult: float = 0.0  # trail distance in daily-ATR multiples (trail_mode="atr")
    scale_out_r: float = 0.0     # take partial profit at this R (0=off; needs >=2 contracts)
    scale_frac: float = 0.5      # fraction of the position taken at the scale-out
    vol_confirm_mult: float = 0.0  # breakout bar volume must exceed this x OR-avg volume (0=off)
    # --- New variables: fib entry / relative volume / volume-delta bias / gap / ATR target ---
    fib_entry: float = 0.5       # entry_mode="fib": retracement ratio to enter on (0.5-0.618); stop = swing low (1.0)
    rvol_min: float = 0.0        # require OR-window volume >= this x its rvol_period-day average (0=off)
    rvol_period: int = 20        # lookback (days) for the relative-volume average
    gap_mode: str = "none"       # overnight gap filter: "none"|"skip_large"|"with"|"fade"
    gap_pct: float = 0.5         # gap threshold in % of prior close (for skip_large)
    target_mode: str = "rr"      # "rr" = reward:risk (default) | "atr" = k x daily ATR
    target_atr_mult: float = 1.0  # ATR multiple for target_mode="atr"
    # bias also accepts "vdelta" (volume-delta pressure); entry_mode also accepts "fib"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _parse_time(s: str) -> dtime:
    return datetime.strptime(s, "%H:%M").time()


def _add_minutes(t: dtime, minutes: int) -> dtime:
    return (datetime.combine(datetime(2000, 1, 1), t) + timedelta(minutes=minutes)).time()


def round_to_tick(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 10)


def _ema(x, span):
    """Exponential moving average over a 1-D array (used by the bias filter)."""
    n = len(x)
    if n == 0:
        return x
    a = 2.0 / (span + 1.0)
    out = np.empty(n, dtype=float)
    out[0] = x[0]
    for j in range(1, n):
        out[j] = a * x[j] + (1.0 - a) * out[j - 1]
    return out


def _sma(x, period):
    """Simple moving average; out[i] uses x[i-period+1 .. i]."""
    n = len(x)
    out = np.full(n, np.nan)
    if n < period:
        return out
    cs = np.cumsum(x)
    out[period - 1] = cs[period - 1] / period
    for i in range(period, n):
        out[i] = (cs[i] - cs[i - period]) / period
    return out


def _atr(h, l, c, period=14):
    """Wilder ATR over daily H/L/C arrays. out[i] uses data through bar i."""
    n = len(h)
    atr = np.full(n, np.nan)
    if n < period + 1:
        return atr
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr[period] = tr[1:period + 1].mean()
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def _adx(h, l, c, period=14):
    """Wilder ADX over daily H/L/C arrays (trend-strength). out[i] valid from ~2*period."""
    n = len(h)
    adx = np.full(n, np.nan)
    if n < 2 * period + 1:
        return adx
    tr = np.zeros(n)
    pdm = np.zeros(n)
    mdm = np.zeros(n)
    for i in range(1, n):
        up = h[i] - h[i - 1]
        dn = l[i - 1] - l[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = np.zeros(n)
    sp = np.zeros(n)
    sm = np.zeros(n)
    atr[period] = tr[1:period + 1].sum()
    sp[period] = pdm[1:period + 1].sum()
    sm[period] = mdm[1:period + 1].sum()
    for i in range(period + 1, n):
        atr[i] = atr[i - 1] - atr[i - 1] / period + tr[i]
        sp[i] = sp[i - 1] - sp[i - 1] / period + pdm[i]
        sm[i] = sm[i - 1] - sm[i - 1] / period + mdm[i]
    with np.errstate(divide="ignore", invalid="ignore"):
        di_p = np.where(atr > 0, 100.0 * sp / atr, 0.0)
        di_m = np.where(atr > 0, 100.0 * sm / atr, 0.0)
        denom = di_p + di_m
        dx = np.where(denom > 0, 100.0 * np.abs(di_p - di_m) / denom, 0.0)
    first = 2 * period
    if first < n:
        adx[first] = dx[period + 1:first + 1].mean()
        for i in range(first + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx


def _looks_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def load_csv(path, tz="America/New_York", source_tz=None, timestamp="open", bar_seconds=None):
    """
    Load an intraday OHLCV CSV into a tz-aware DataFrame.

    Handles the common formats automatically:
      * comma / semicolon / tab separated
      * with or without a header row
      * single "datetime" column, or separate date + time columns
      * NinjaTrader export style: `yyyyMMdd HHmmss;O;H;L;C;V`

    Parameters
    ----------
    tz : the ANALYSIS timezone — times like or_start/exit_time are interpreted in
         this zone (default US/Eastern, the CME RTH reference).
    source_tz : the timezone the file's timestamps are ACTUALLY in. NinjaTrader
         historical exports are commonly in UTC; pass source_tz="UTC" and the data
         is converted to `tz`. If None, the file is assumed to already be in `tz`.
    timestamp : "open"  -> each row is stamped at the bar's START
                            (FirstRate, Polygon, yfinance, most CSVs)
                "close" -> stamped at the bar's END (NinjaTrader exports)
                We normalise everything to start-of-bar internally.
    bar_seconds : bar length in seconds; auto-detected if None.
    """
    # ---- SEP fix: use csv.Sniffer over first 4 KB for reliable delimiter detection ----
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        sample = f.read(4096)
    head = sample.split("\n")[0]

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        sep = dialect.delimiter
    except csv.Error:
        # Fallback: substring test on first line
        sep = ";" if ";" in head else ("\t" if "\t" in head else ",")

    # ---- HDR fix: keyword check + non-numeric OHLC-position check for abbreviated headers ----
    header_words = {"open", "high", "low", "close", "date", "time",
                    "timestamp", "datetime", "vol", "volume"}
    first_cells = [c.strip().lower() for c in head.strip().split(sep)]

    has_header = any(c in header_words for c in first_cells)

    # Also catch abbreviated headers (o,h,l,c,v) where no cell matches the keyword list:
    # If 4+ cells at positions 1-4 are all non-numeric, the row is a header, not data.
    if not has_header and len(first_cells) >= 5:
        ohlc_candidates = first_cells[1:5]
        if all(not _looks_numeric(c) for c in ohlc_candidates):
            has_header = True

    df = pd.read_csv(path, sep=sep, header=0 if has_header else None)

    if has_header:
        df.columns = [str(c).strip().lower() for c in df.columns]
        cols = set(df.columns)
        if "timestamp" in cols:
            dt = pd.to_datetime(df["timestamp"], errors="coerce")
        elif "datetime" in cols:
            dt = pd.to_datetime(df["datetime"], errors="coerce")
        elif "date" in cols and "time" in cols:
            dt = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str),
                                errors="coerce")
        else:                                   # assume first column is the datetime
            dt = pd.to_datetime(df.iloc[:, 0], errors="coerce")
        df = df.rename(columns={"vol": "volume"})
        ohlc = df[["open", "high", "low", "close"]].astype(float)
        vol = df["volume"].astype(float) if "volume" in df.columns else 0.0
    else:
        ncols = df.shape[1]
        if ncols >= 7:          # date, time, O, H, L, C, V
            dt = pd.to_datetime(df[0].astype(str) + " " + df[1].astype(str), errors="coerce")
            o, h, l, c = 2, 3, 4, 5
            vol = df[6].astype(float)
        else:                   # datetime, O, H, L, C [, V]
            dt = pd.to_datetime(df[0], errors="coerce")
            if dt.isna().mean() > 0.5:          # retry NinjaTrader's compact format
                dt = pd.to_datetime(df[0].astype(str), format="%Y%m%d %H%M%S", errors="coerce")
            o, h, l, c = 1, 2, 3, 4
            vol = df[5].astype(float) if ncols >= 6 else 0.0
        ohlc = df[[o, h, l, c]].astype(float)
        ohlc.columns = ["open", "high", "low", "close"]

    out = ohlc.copy()
    out["volume"] = vol
    out.index = dt
    out = out[~out.index.isna()].sort_index()

    # ---- DEDUP fix: deduplicate on raw timestamps BEFORE DST transforms ----
    out = out[~out.index.duplicated(keep="first")]

    # ---- timezone ----
    # Localize naive timestamps to their SOURCE zone (e.g. UTC for NinjaTrader
    # exports), then convert to the ANALYSIS zone so 09:30 means the cash open.
    src_tz = source_tz or tz
    if out.index.tz is None:
        # DST fix: use "infer" instead of "NaT" so fall-back-hour bars are preserved
        # (ambiguous="NaT" silently deleted ~1 h of data on US November fall-back days)
        out.index = out.index.tz_localize(src_tz, nonexistent="shift_forward", ambiguous="infer")
    out.index = out.index.tz_convert(tz)

    # ---- normalise close-stamped bars to start-of-bar ----
    if timestamp == "close":
        if bar_seconds is None:
            diffs = out.index.to_series().diff().dropna()
            bar_seconds = int(diffs.mode().iloc[0].total_seconds()) if len(diffs) else 60
        out.index = out.index - pd.Timedelta(seconds=bar_seconds)

    # Post-transform dedup: DST spring-forward can manufacture collisions; warn if any remain.
    n_before = len(out)
    out = out[~out.index.duplicated(keep="first")]
    if len(out) < n_before:
        warnings.warn(
            f"load_csv: dropped {n_before - len(out)} duplicate timestamp(s) after DST shift "
            f"in '{path}'. Check for a DST spring-forward day in your data.",
            stacklevel=2,
        )

    return out


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def _time_to_sec(s: str) -> int:
    t = _parse_time(s)
    return t.hour * 3600 + t.minute * 60 + t.second


def prepare_days(df: pd.DataFrame):
    """
    Split a tz-aware OHLCV frame into per-day numpy arrays ONCE so the optimizer
    can sweep hundreds of parameter sets without re-grouping the DataFrame every
    time. Returns a list of per-day dicts. The trade logic in run_prepared() is
    identical to the old per-row pass -- this is purely a speed refactor.
    """
    df = df.sort_index()
    op = df["open"].to_numpy(dtype=float)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    cl = df["close"].to_numpy(dtype=float)
    vl = df["volume"].to_numpy(dtype=float) if "volume" in df.columns else np.zeros(len(df))
    idx = df.index
    sec = (idx.hour * 3600 + idx.minute * 60 + idx.second).to_numpy()

    days = []
    for day, pos in df.groupby(df.index.date).indices.items():
        pos = np.asarray(pos)
        days.append({
            "date": day,
            "sec": sec[pos],
            "open": op[pos], "high": hi[pos], "low": lo[pos], "close": cl[pos],
            "vol": vl[pos], "time": idx[pos],
        })
    return days


def _find_entry(start_k, n, op, hi, lo, cl, mode, allow_long, allow_short,
                long_trig, short_trig, slip, entry_limit=None, wvol=None, vol_thresh=0.0,
                or_low=None, or_high=None, fib_entry=0.5):
    """
    Scan window bars from start_k; return (entry_idx, direction, fill) for the first
    qualifying entry, or (None, None, None). Entry style depends on `mode`:
      stop    : first TOUCH of the level (current behaviour; enters on the first poke)
      close   : a bar must CLOSE beyond the level (filters wick-only false breaks)
      rebreak : break -> a bar closes back INSIDE -> break again, then enter
      retest  : a bar closes beyond -> price pulls back to the level -> enter there
    Long and short each run their own state machine; whichever fires first wins
    (nearest-to-open on a same-bar tie). No NEW entry is opened at/after entry_limit.
    """
    if entry_limit is None or entry_limit > n:
        entry_limit = n
    ls = ss = 0  # per-direction state phase
    lv_ok = sv_ok = True  # retest/fib: did the breakout (confirmation) bar pass volume?
    fib_hi = -1e18        # running swing high after a long breakout (fib mode)
    fib_lo = 1e18         # running swing low after a short breakout (fib mode)
    for k in range(start_k, entry_limit):
        bo, bh, bl, bc = op[k], hi[k], lo[k], cl[k]
        fl = fs = False
        el = es = 0.0

        if allow_long:
            if mode == "stop":
                if bh >= long_trig:
                    fl, el = True, max(bo, long_trig) + slip
            elif mode == "close":
                if bc >= long_trig:
                    fl, el = True, bc + slip
            elif mode == "rebreak":
                if ls == 0:
                    if bh >= long_trig:
                        ls = 1
                elif ls == 1:
                    if bc < long_trig:
                        ls = 2
                else:
                    if bh >= long_trig:
                        fl, el = True, max(bo, long_trig) + slip
            elif mode == "retest":
                if ls == 0:
                    if bc >= long_trig:
                        ls = 1
                        lv_ok = vol_thresh <= 0.0 or (wvol is not None and wvol[k] >= vol_thresh)
                else:
                    if bl <= long_trig:
                        fl, el = True, long_trig
            elif mode == "fib":
                if ls == 0:
                    if bh >= long_trig:                 # breakout up -> start tracking the swing
                        ls = 1
                        fib_hi = bh
                        lv_ok = vol_thresh <= 0.0 or (wvol is not None and wvol[k] >= vol_thresh)
                else:
                    if bh > fib_hi:
                        fib_hi = bh
                    ent = fib_hi - fib_entry * (fib_hi - or_low)   # 0.5-0.618 retracement
                    if bl <= ent:                       # pulled back into the zone -> limit fill
                        fl, el = True, min(bo, ent)

        if allow_short:
            if mode == "stop":
                if bl <= short_trig:
                    fs, es = True, min(bo, short_trig) - slip
            elif mode == "close":
                if bc <= short_trig:
                    fs, es = True, bc - slip
            elif mode == "rebreak":
                if ss == 0:
                    if bl <= short_trig:
                        ss = 1
                elif ss == 1:
                    if bc > short_trig:
                        ss = 2
                else:
                    if bl <= short_trig:
                        fs, es = True, min(bo, short_trig) - slip
            elif mode == "retest":
                if ss == 0:
                    if bc <= short_trig:
                        ss = 1
                        sv_ok = vol_thresh <= 0.0 or (wvol is not None and wvol[k] >= vol_thresh)
                else:
                    if bh >= short_trig:
                        fs, es = True, short_trig
            elif mode == "fib":
                if ss == 0:
                    if bl <= short_trig:                # breakdown -> start tracking the swing
                        ss = 1
                        fib_lo = bl
                        sv_ok = vol_thresh <= 0.0 or (wvol is not None and wvol[k] >= vol_thresh)
                else:
                    if bl < fib_lo:
                        fib_lo = bl
                    ent = fib_lo + fib_entry * (or_high - fib_lo)  # bounce into the zone
                    if bh >= ent:
                        fs, es = True, max(bo, ent)

        # volume confirmation: the BREAKOUT bar must trade enough volume. For retest
        # entries the breakout bar precedes the (low-volume) pullback fill bar, so use
        # the flag captured at the confirmation step instead of testing the fill bar.
        if vol_thresh > 0.0 and wvol is not None:
            if mode in ("retest", "fib"):
                if fl and not lv_ok:
                    fl = False
                if fs and not sv_ok:
                    fs = False
            elif wvol[k] < vol_thresh:
                fl = fs = False

        if fl and fs:
            if abs(bo - long_trig) <= abs(bo - short_trig):
                return k, "long", el
            return k, "short", es
        if fl:
            return k, "long", el
        if fs:
            return k, "short", es
    return None, None, None


def _manage_exit(direction, entry_idx, fill, stop, target, target_valid, qty,
                 op, hi, lo, cl, n, pessimistic, slip, risk_pts,
                 breakeven_r, trail_dist, scale_out_r, scale_frac):
    """
    Manage a trade from entry to exit with optional breakeven, trailing stop, and
    partial scale-out. Returns (exit_idx, exit_price, reason, gross_pts), where
    gross_pts is the SUM over all contracts of (exit - fill) in points (signed for
    direction). With breakeven/trail/scale all OFF this equals qty*(exit - fill) and
    reproduces the plain stop/target/time logic exactly.

    Conservative intrabar ordering: the stop is resolved before scale/target (so a
    bar that hits both is treated pessimistically); breakeven and the trailing stop
    tighten using each COMPLETED bar, so they never peek ahead.
    """
    long = direction == "long"
    do_scale = scale_out_r > 0 and qty >= 2
    qty1 = max(1, int(qty * scale_frac)) if do_scale else 0
    qty_open = qty
    scaled = False
    scale_price = (fill + scale_out_r * risk_pts) if long else (fill - scale_out_r * risk_pts)
    be_price = (fill + breakeven_r * risk_pts) if long else (fill - breakeven_r * risk_pts)
    cur_stop = stop
    hwm = fill
    gross_pts = 0.0

    start = entry_idx if pessimistic else entry_idx + 1
    for j in range(start, n):
        bh, bl = hi[j], lo[j]
        if long:
            hit_stop = bl <= cur_stop
            hit_tgt = target_valid and bh >= target
            hit_scale = do_scale and not scaled and bh >= scale_price
        else:
            hit_stop = bh >= cur_stop
            hit_tgt = target_valid and bl <= target
            hit_scale = do_scale and not scaled and bl <= scale_price

        if hit_stop and hit_tgt:
            final = "stop" if pessimistic else "target"
        elif hit_stop:
            final = "stop"
        elif hit_tgt:
            final = "target"
        else:
            final = None

        if final == "stop":
            px = (cur_stop - slip) if long else (cur_stop + slip)
            gross_pts += qty_open * ((px - fill) if long else (fill - px))
            return j, px, ("scale+stop" if scaled else "stop"), gross_pts

        if hit_scale:                                   # favorable: bank the partial
            gross_pts += qty1 * ((scale_price - fill) if long else (fill - scale_price))
            qty_open -= qty1
            scaled = True
        if final == "target":
            gross_pts += qty_open * ((target - fill) if long else (fill - target))
            return j, target, ("scale+target" if scaled else "target"), gross_pts

        # tighten the stop using this completed bar (no lookahead)
        if long:
            if bh > hwm:
                hwm = bh
            if breakeven_r > 0 and hwm >= be_price and cur_stop < fill:
                cur_stop = fill
            if trail_dist > 0 and hwm - trail_dist > cur_stop:
                cur_stop = hwm - trail_dist
        else:
            if bl < hwm:
                hwm = bl
            if breakeven_r > 0 and hwm <= be_price and cur_stop > fill:
                cur_stop = fill
            if trail_dist > 0 and hwm + trail_dist < cur_stop:
                cur_stop = hwm + trail_dist

    px = float(cl[n - 1])                               # time-based exit
    gross_pts += qty_open * ((px - fill) if long else (fill - px))
    return n - 1, px, ("scale+time" if scaled else "time"), gross_pts


def run_backtest(df: pd.DataFrame, p: Params):
    """Run the ORB over `df`. Returns (trades_df, metrics_dict)."""
    return run_prepared(prepare_days(df), p)


def run_prepared(days, p: Params):
    """Run the ORB over pre-split per-day arrays (see prepare_days)."""
    spec = INSTRUMENTS[p.instrument]
    tick = spec["tick_size"]
    point_value = spec["tick_value"] / spec["tick_size"]
    offset = p.offset_ticks * tick
    slip = p.slippage_ticks * tick

    or_start_sec = _time_to_sec(p.or_start)
    or_end_sec = or_start_sec + p.or_minutes * 60
    exit_sec = _time_to_sec(p.exit_time)

    trades = []

    # --- directional bias (trend filter) precompute ---
    bias = p.bias
    ema_arr = None
    if bias in ("ema_slope", "ema_price"):
        closes = np.array([float(d["close"][-1]) for d in days]) if days else np.array([])
        ema_arr = _ema(closes, p.ema_period)
    slope_L = max(1, p.bias_slope_lookback)
    base_long = p.direction in ("both", "long")
    base_short = p.direction in ("both", "short")

    # --- daily indicators for stop_mode / regime (computed once; used at [i-1] = no lookahead) ---
    atr_arr = adx_arr = sma_arr = d_close = gap_arr = rvol_avg = or_vol_arr = None
    need_daily = (p.stop_mode == "atr" or p.trail_mode == "atr" or p.target_mode == "atr"
                  or p.regime in ("adx", "ma") or p.gap_mode != "none")
    if need_daily and days:
        d_high = np.array([float(d["high"].max()) for d in days])
        d_low = np.array([float(d["low"].min()) for d in days])
        d_close = np.array([float(d["close"][-1]) for d in days])
        if p.stop_mode == "atr" or p.trail_mode == "atr" or p.target_mode == "atr":
            atr_arr = _atr(d_high, d_low, d_close, p.atr_period)
        if p.regime == "adx":
            adx_arr = _adx(d_high, d_low, d_close, 14)
        if p.regime == "ma":
            sma_arr = _sma(d_close, p.regime_ma_period)
        if p.gap_mode != "none":
            d_open = np.array([float(d["open"][0]) for d in days])
            gap_arr = np.full(len(days), np.nan)
            with np.errstate(divide="ignore", invalid="ignore"):
                gap_arr[1:] = (d_open[1:] - d_close[:-1]) / d_close[:-1] * 100.0
    # relative-volume: OR-window volume vs its trailing average (no lookahead -> prior days)
    if p.rvol_min > 0 and days:
        or_vol_arr = np.array([float(d["vol"][(d["sec"] >= or_start_sec) & (d["sec"] < or_end_sec)].sum())
                               for d in days])
        rvol_avg = np.full(len(days), np.nan)
        for ii in range(p.rvol_period, len(days)):
            rvol_avg[ii] = or_vol_arr[ii - p.rvol_period:ii].mean()
    cutoff_sec = _time_to_sec(p.entry_cutoff) if p.entry_cutoff else None

    for i, day in enumerate(days):
        sec = day["sec"]

        # Opening range = bars in [or_start, or_end)
        or_mask = (sec >= or_start_sec) & (sec < or_end_sec)
        if not or_mask.any():
            continue
        or_high = float(day["high"][or_mask].max())
        or_low = float(day["low"][or_mask].min())
        if not (or_high > or_low):
            continue

        # ---- Volatility filter: skip days whose opening range is too wide (choppy /
        # false-breakout prone) or too narrow. Decided at OR close => no lookahead. ----
        or_range_pts = or_high - or_low
        if p.max_or_points and or_range_pts > p.max_or_points:
            continue
        if p.min_or_points and or_range_pts < p.min_or_points:
            continue

        # ---- Event-day skip (algorithmic NFP=1st Friday, OpEx=3rd Friday) ----
        if p.skip_nfp or p.skip_opex:
            wd = day["date"].weekday()
            if wd == 4:
                dom = day["date"].day
                if p.skip_nfp and 1 <= dom <= 7:
                    continue
                if p.skip_opex and 15 <= dom <= 21:
                    continue

        # ---- Regime filter: only trade in a trending market (uses prior day -> no lookahead) ----
        if p.regime == "adx":
            if i < 1 or adx_arr is None or np.isnan(adx_arr[i - 1]) or adx_arr[i - 1] < p.regime_adx_min:
                continue
        elif p.regime == "ma":
            kk = 5
            if (i - 1 - kk < 0 or sma_arr is None
                    or np.isnan(sma_arr[i - 1]) or np.isnan(sma_arr[i - 1 - kk])):
                continue
            c1, m1, m0 = d_close[i - 1], sma_arr[i - 1], sma_arr[i - 1 - kk]
            if not ((c1 > m1 and m1 > m0) or (c1 < m1 and m1 < m0)):
                continue

        # ---- Relative-volume filter: only trade when participation is elevated ----
        if p.rvol_min > 0:
            if (i < p.rvol_period or rvol_avg is None or np.isnan(rvol_avg[i])
                    or rvol_avg[i] <= 0 or or_vol_arr[i] / rvol_avg[i] < p.rvol_min):
                continue

        # ---- Directional bias: only take the trend-side breakout. Everything used
        # here is known at OR close (prior daily EMA / VWAP-so-far) -> no lookahead. ----
        allow_long, allow_short = base_long, base_short
        if bias != "none":
            or_close_px = float(day["close"][or_mask][-1])
            bdir = None
            if bias == "ema_slope":
                if i - 1 - slope_L >= 0:
                    bdir = "long" if ema_arr[i - 1] > ema_arr[i - 1 - slope_L] else "short"
            elif bias == "ema_price":
                if i - 1 >= 0:
                    bdir = "long" if or_close_px > ema_arr[i - 1] else "short"
            elif bias in ("vwap", "vwap_slope"):
                # F2 fix: strictly BEFORE the OR close (sec < or_end_sec), matching the
                # OR mask. The bar stamped at or_end_sec is the first TRADEABLE bar, so
                # including it would be same-bar lookahead.
                upto = sec < or_end_sec
                vv = day["vol"][upto]
                if vv.sum() > 0:
                    tp = (day["high"][upto] + day["low"][upto] + day["close"][upto]) / 3.0
                    if bias == "vwap":
                        vwap = float((tp * vv).sum() / vv.sum())
                        bdir = "long" if or_close_px > vwap else "short"
                    else:  # vwap_slope: did the running VWAP rise across the OR?
                        cw = np.cumsum(vv)
                        vws = np.cumsum(tp * vv) / np.where(cw == 0, np.nan, cw)
                        s_up = sec[upto]
                        si = int(np.searchsorted(s_up, or_start_sec, side="left"))
                        if 0 <= si < len(vws) - 1 and not np.isnan(vws[si]):
                            bdir = "long" if vws[-1] > vws[si] else "short"
            elif bias == "vdelta":
                # poor-man's cumulative delta over the OR: weight each bar's volume by
                # where it closed in its range (+1 at the high = buying, -1 at the low).
                orh = day["high"][or_mask]
                orl = day["low"][or_mask]
                orc = day["close"][or_mask]
                orv = day["vol"][or_mask]
                rng = orh - orl
                with np.errstate(divide="ignore", invalid="ignore"):
                    pos = np.where(rng > 0, 2.0 * (orc - orl) / rng - 1.0, 0.0)
                netdelta = float(np.sum(orv * pos))
                bdir = "long" if netdelta > 0 else ("short" if netdelta < 0 else None)
            if bdir is None:
                continue                                  # can't determine bias -> stand aside
            allow_long = allow_long and (bdir == "long")
            allow_short = allow_short and (bdir == "short")
            if not (allow_long or allow_short):
                continue

        # ---- Overnight gap filter ----
        if p.gap_mode != "none" and gap_arr is not None and i >= 1 and not np.isnan(gap_arr[i]):
            g = gap_arr[i]
            if p.gap_mode == "skip_large":
                if abs(g) > p.gap_pct:
                    continue
            elif p.gap_mode == "with":          # only trade in the gap's direction
                if g > 0:
                    allow_short = False
                elif g < 0:
                    allow_long = False
            elif p.gap_mode == "fade":          # only trade against the gap
                if g > 0:
                    allow_long = False
                elif g < 0:
                    allow_short = False
            if not (allow_long or allow_short):
                continue

        # Tradeable window = [or_end, exit_time) -- inclusive="left" (EX1 fix), so the
        # last accepted bar starts strictly before exit_time, matching NT's >= ExitTime.
        widx = np.nonzero((sec >= or_end_sec) & (sec < exit_sec))[0]
        if widx.size == 0:
            continue
        op = day["open"][widx]
        hi = day["high"][widx]
        lo = day["low"][widx]
        cl = day["close"][widx]
        tm = day["time"][widx]
        n = widx.size
        entry_limit = int(np.searchsorted(sec[widx], cutoff_sec, side="left")) if cutoff_sec else n
        wvol = day["vol"][widx]
        if p.vol_confirm_mult > 0:
            orv = day["vol"][or_mask]
            vol_thresh = p.vol_confirm_mult * float(orv.mean()) if orv.size else 0.0
        else:
            vol_thresh = 0.0

        long_trig = round_to_tick(or_high + offset, tick)
        short_trig = round_to_tick(or_low - offset, tick)

        # ---- Stop placement (default "or" = opposite OR extreme; reproduces baseline) ----
        if p.stop_mode == "points":
            long_stop = round_to_tick(long_trig - p.stop_points, tick)
            short_stop = round_to_tick(short_trig + p.stop_points, tick)
        elif p.stop_mode == "atr":
            if i < 1 or atr_arr is None or np.isnan(atr_arr[i - 1]) or atr_arr[i - 1] <= 0:
                continue
            d_stop = p.stop_atr_mult * atr_arr[i - 1]
            long_stop = round_to_tick(long_trig - d_stop, tick)
            short_stop = round_to_tick(short_trig + d_stop, tick)
        elif p.stop_mode == "or_frac":
            long_stop = round_to_tick(long_trig - p.stop_or_frac * or_range_pts, tick)
            short_stop = round_to_tick(short_trig + p.stop_or_frac * or_range_pts, tick)
        else:  # "or"
            long_stop = round_to_tick(or_low - offset, tick)
            short_stop = round_to_tick(or_high + offset, tick)
        long_risk = long_trig - long_stop
        short_risk = short_stop - short_trig
        # F1(sizing) fix: a tiny points/or_frac stop can round onto the trigger -> zero
        # risk -> degenerate instant stop-out. Floor the stop at one tick.
        if long_risk <= 0:
            long_stop = round_to_tick(long_trig - tick, tick)
            long_risk = long_trig - long_stop
        if short_risk <= 0:
            short_stop = round_to_tick(short_trig + tick, tick)
            short_risk = short_stop - short_trig
        # ---- Target placement: reward:risk (default) or k x daily ATR ----
        if p.target_mode == "atr":
            if atr_arr is None or i < 1 or np.isnan(atr_arr[i - 1]) or atr_arr[i - 1] <= 0:
                continue
            t_dist = p.target_atr_mult * atr_arr[i - 1]
            long_target = round_to_tick(long_trig + t_dist, tick)
            short_target = round_to_tick(short_trig - t_dist, tick)
        else:
            long_target = round_to_tick(long_trig + p.rr * long_risk, tick)
            short_target = round_to_tick(short_trig - p.rr * short_risk, tick)

        trades_done = 0
        k = 0
        while trades_done < p.max_trades and k < n:
            # ---- find the entry from bar k onward (style depends on p.entry_mode) ----
            entry_idx, direction, fill = _find_entry(
                k, n, op, hi, lo, cl, p.entry_mode,
                allow_long, allow_short, long_trig, short_trig, slip, entry_limit,
                wvol, vol_thresh, or_low, or_high, p.fib_entry)
            if entry_idx is None:
                break

            if direction == "long":
                stop, target = long_stop, long_target
                realized_risk = fill - (long_stop - slip)   # LA2: realized fill-to-stop risk
            else:
                stop, target = short_stop, short_target
                realized_risk = (short_stop + slip) - fill
            if realized_risk <= 0:
                realized_risk = long_risk if direction == "long" else short_risk

            # LA1: a gap past the target invalidates a "target" exit (it would be behind fill).
            target_valid = (target > fill) if direction == "long" else (target < fill)

            # ---- position size (computed before exit mgmt -- scale-out needs it) ----
            if p.risk_dollars > 0 and realized_risk > 0:
                rpc = realized_risk * point_value          # $ risk for one contract
                qty = max(1, min(p.max_contracts, int(p.risk_dollars / rpc)))
            else:
                qty = p.contracts

            # ---- trailing distance for this trade ----
            if p.trail_mode == "ticks":
                trail_dist = p.trail_ticks * tick
            elif p.trail_mode == "atr" and atr_arr is not None and i >= 1 and not np.isnan(atr_arr[i - 1]):
                trail_dist = p.trail_atr_mult * atr_arr[i - 1]
            else:
                trail_dist = 0.0

            exit_idx, exit_price, exit_reason, gross_pts = _manage_exit(
                direction, entry_idx, fill, stop, target, target_valid, qty,
                op, hi, lo, cl, n, p.pessimistic, slip, realized_risk,
                p.breakeven_r, trail_dist, p.scale_out_r, p.scale_frac)

            pts = gross_pts / qty if qty else 0.0
            gross = gross_pts * point_value
            commission = p.commission_rt * qty
            net = gross - commission

            trades.append({
                "date": day["date"],
                "direction": direction,
                "entry_time": tm[entry_idx],
                "entry": fill,
                "exit_time": tm[exit_idx],
                # ME-5 fix: report the blended exit so 'exit' is consistent with 'points'
                # on scaled trades (identical to the single exit price when not scaled).
                "exit": (fill + pts) if direction == "long" else (fill - pts),
                "reason": exit_reason,
                "points": pts,
                "R": pts / realized_risk if realized_risk > 0 else 0.0,
                "contracts": qty,
                "gross": gross,
                "commission": commission,
                "net": net,
                "or_high": or_high,
                "or_low": or_low,
                "range_pts": or_high - or_low,
            })

            trades_done += 1
            k = exit_idx + 1

    trades_df = pd.DataFrame(trades)
    return trades_df, compute_metrics(trades_df)


def compute_metrics(trades: pd.DataFrame) -> dict:
    keys = ["trades", "wins", "losses", "win_rate", "gross", "net", "profit_factor",
            "expectancy", "avg_R", "avg_win", "avg_loss", "best", "worst",
            "max_drawdown", "sharpe"]
    if trades is None or len(trades) == 0:
        return {k: 0.0 for k in keys}

    n = len(trades)
    wins = trades[trades["net"] > 0]
    # LA3 fix: scratch trades (net == 0) excluded from loss bucket so they don't
    # inflate profit_factor. Only genuine losses (net < 0) count against gross loss.
    losses = trades[trades["net"] < 0]
    gp = wins["net"].sum()
    gl = abs(losses["net"].sum())

    eq = trades["net"].cumsum()
    dd = (eq - eq.cummax()).min()

    daily = trades.groupby("date")["net"].sum()
    sharpe = (daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0

    # LA3 fix: return nan instead of inf when there are no losing trades so the
    # optimizer doesn't rank zero-loss / tiny-sample cells as best-possible.
    pf = float(gp / gl) if gl > 0 else float("nan")

    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / n * 100.0,
        "gross": float(trades["gross"].sum()),
        "net": float(trades["net"].sum()),
        "profit_factor": pf,
        "expectancy": float(trades["net"].mean()),
        "avg_R": float(trades["R"].mean()),
        "avg_win": float(wins["net"].mean()) if len(wins) else 0.0,
        "avg_loss": float(losses["net"].mean()) if len(losses) else 0.0,
        "best": float(trades["net"].max()),
        "worst": float(trades["net"].min()),
        "max_drawdown": float(dd),
        "sharpe": float(sharpe),
    }


def format_metrics(m: dict, p: Params = None) -> str:
    pf = m["profit_factor"]
    pf_str = f"{pf:.2f}" if math.isfinite(pf) else "n/a (no losses)"
    lines = []
    if p is not None:
        lines.append(f"  Instrument        : {p.instrument}   "
                     f"OR {p.or_minutes}m from {p.or_start}   RR {p.rr}   "
                     f"offset {p.offset_ticks}t   dir {p.direction}")
    lines += [
        f"  Trades            : {m['trades']:.0f}  "
        f"(W {m['wins']:.0f} / L {m['losses']:.0f})",
        f"  Win rate          : {m['win_rate']:.1f}%",
        f"  Net P&L           : ${m['net']:,.2f}",
        f"  Profit factor     : {pf_str}",
        f"  Expectancy/trade  : ${m['expectancy']:.2f}   ({m['avg_R']:.2f} R)",
        f"  Avg win / avg loss: ${m['avg_win']:.2f} / ${m['avg_loss']:.2f}",
        f"  Best / worst      : ${m['best']:.2f} / ${m['worst']:.2f}",
        f"  Max drawdown      : ${m['max_drawdown']:,.2f}",
        f"  Sharpe (daily)    : {m['sharpe']:.2f}",
    ]
    return "\n".join(lines)
