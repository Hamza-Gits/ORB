"""
orb_montecarlo.py
=================
Monte Carlo robustness + prop-survival test for a CHOSEN ORB config.

The segment/robustness test proves the edge held in each historical chunk -- but
history is ONE ordering of the trades. Monte Carlo asks the question that actually
decides prop survival: across thousands of plausible re-orderings of the SAME
trades, how wide is the spread of annual returns, and how often does an end-of-day
drawdown blow the account before it passes?

What it does
------------
1. Runs the backtest for the given config and pulls the real per-trade P&L
   sequence (1 contract, costs included).
2. Bootstrap-resamples that sequence thousands of times to build distributions of:
     - annual net P&L (5th / 50th / 95th percentile)
     - max END-OF-DAY trailing drawdown (median / 95th / 99th / worst)
3. Simulates the actual prop EVAL as a race: each path trades day-by-day until it
   either hits the profit target (PASS), breaches the trailing EOD loss limit
   (BLOW), or runs out of days (TIMEOUT). Reports P(pass)/P(blow)/P(timeout) and
   median trading-days-to-pass, for both the 25K and 50K FLEX accounts.

Resampling
----------
  --mode block   (default)  resample consecutive BLOCKS of trades, so losing
                            streaks stay clustered -> realistic, conservative DD.
  --mode iid                shuffle individual trades (destroys streaks; optimistic).

EOD drawdown model
------------------
These FLEX accounts measure drawdown at the CLOSE and trail the peak end-of-day
balance. The strategy is flat overnight and takes <=1 trade/day, so the per-trade
P&L sequence IS the daily-close sequence. We trail the peak EOD balance and flag a
breach when (peak - equity) >= the limit. This is the strict (always-trailing)
interpretation; a static-from-start number is also printed to bracket the risk.

    python orb_montecarlo.py --csv MNQ_full_1min.csv --instrument MNQ \
        --or-minutes 15 --offset-ticks 2 --direction both --bias vwap_slope \
        --max-or-points 130 --regime none --target atr1.5 --contracts 1
"""

import argparse
from dataclasses import replace

import numpy as np
import pandas as pd

from orb_strategy import INSTRUMENTS, Params, load_csv, run_backtest


# FLEX EVAL account specs: (label, profit target $, max EOD loss $, micros allowed)
ACCOUNTS = [
    ("25K", 1_250.0, 1_000.0, 20),
    ("50K", 3_000.0, 2_000.0, 40),
]


def build_params(a) -> Params:
    """Construct Params from the core dims + the composite 'target' token."""
    p = Params(
        instrument=a.instrument,
        or_minutes=a.or_minutes,
        offset_ticks=a.offset_ticks,
        direction=a.direction,
        bias=a.bias,
        max_or_points=a.max_or_points,
        regime=a.regime,
        contracts=a.contracts,
        commission_rt=a.commission_rt,
        slippage_ticks=a.slippage_ticks,
    )
    t = str(a.target)
    if t.startswith("atr"):
        p = replace(p, target_mode="atr", target_atr_mult=float(t[3:]))
    elif t.startswith("rr"):
        p = replace(p, target_mode="rr", rr=float(t[2:]))
    return p


def block_indices(n_src, n_out, block, rng):
    """Indices for a block bootstrap: stitch random consecutive runs of `block`."""
    if block <= 1 or n_src <= block:
        return rng.integers(0, n_src, size=n_out)
    n_blocks = int(np.ceil(n_out / block))
    starts = rng.integers(0, n_src - block + 1, size=n_blocks)
    idx = (starts[:, None] + np.arange(block)[None, :]).ravel()
    return idx[:n_out]


def max_trailing_eod_dd(equity):
    """Most negative (peak-so-far - equity); peak seeded at 0 = start balance."""
    peak = np.maximum.accumulate(np.concatenate(([0.0], equity)))
    return float((np.concatenate(([0.0], equity)) - peak).min())


def pct(a, q):
    return float(np.percentile(a, q))


def simulate_outcome_paths(pnl, n_per_path, n_paths, mode, block, rng):
    """Resample n_paths equity paths of length n_per_path; return (nets, max_dds)."""
    nets = np.empty(n_paths)
    dds = np.empty(n_paths)
    for k in range(n_paths):
        if mode == "iid":
            idx = rng.integers(0, len(pnl), size=n_per_path)
        else:
            idx = block_indices(len(pnl), n_per_path, block, rng)
        path = pnl[idx]
        eq = np.cumsum(path)
        nets[k] = eq[-1]
        dds[k] = max_trailing_eod_dd(eq)
    return nets, dds


def simulate_eval(pnl, target, limit, max_days, n_paths, mode, block, rng, lock=True):
    """
    Race each path: trade day-by-day (eq = profit since start) until eq hits
    +target (PASS), the trailing EOD drawdown floor is breached (BLOW), or max_days
    is reached (TIMEOUT). Returns (p_pass, p_blow, p_timeout, median_days_to_pass).

    Drawdown floor (in profit-since-start coords):
      lock=True  (realistic FLEX): floor = min(0, peak - limit) -- trails the peak
                 but never rises above the START balance, so once you've banked
                 `limit` of peak profit the account can't fall below start.
      lock=False (strict/conservative): floor = peak - limit -- trails forever.
    """
    n_pass = n_blow = n_timeout = 0
    days_to_pass = []
    for _ in range(n_paths):
        if mode == "iid":
            idx = rng.integers(0, len(pnl), size=max_days)
        else:
            idx = block_indices(len(pnl), max_days, block, rng)
        path = pnl[idx]
        eq = 0.0
        peak = 0.0
        outcome = "timeout"
        for d in range(max_days):
            eq += path[d]
            if eq > peak:
                peak = eq
            floor = (min(0.0, peak - limit) if lock else peak - limit)
            if eq <= floor:                  # EOD drawdown breach -> account dead
                outcome = "blow"
                break
            if eq >= target:                 # hit profit target -> eval passed
                outcome = "pass"
                days_to_pass.append(d + 1)
                break
        if outcome == "pass":
            n_pass += 1
        elif outcome == "blow":
            n_blow += 1
        else:
            n_timeout += 1
    med = float(np.median(days_to_pass)) if days_to_pass else float("nan")
    return n_pass / n_paths, n_blow / n_paths, n_timeout / n_paths, med


def main():
    ap = argparse.ArgumentParser(description="Monte Carlo robustness + prop-survival test")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--instrument", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--or-minutes", type=int, default=15, dest="or_minutes")
    ap.add_argument("--offset-ticks", type=int, default=0, dest="offset_ticks")
    ap.add_argument("--direction", default="both", choices=["both", "long", "short"])
    ap.add_argument("--bias", default="none",
                    choices=["none", "ema_slope", "ema_price", "vwap", "vwap_slope", "vdelta"])
    ap.add_argument("--max-or-points", type=float, default=0.0, dest="max_or_points")
    ap.add_argument("--regime", default="none", choices=["none", "adx", "ma"])
    ap.add_argument("--target", default="rr1.0",
                    help="composite target token: rrX.X (reward:risk) or atrX.X (ATR target)")
    ap.add_argument("--contracts", type=int, default=1)
    ap.add_argument("--commission-rt", type=float, default=1.24, dest="commission_rt")
    ap.add_argument("--slippage-ticks", type=int, default=1, dest="slippage_ticks")
    ap.add_argument("--paths", type=int, default=10_000, help="Monte Carlo paths")
    ap.add_argument("--mode", default="block", choices=["block", "iid"])
    ap.add_argument("--block", type=int, default=10, help="block length for block bootstrap")
    ap.add_argument("--max-eval-days", type=int, default=252, dest="max_eval_days",
                    help="trading days allowed to pass the eval before TIMEOUT")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--tz", default="America/New_York")
    ap.add_argument("--source-tz", default=None, dest="source_tz")
    ap.add_argument("--timestamp", default="open", choices=["open", "close"])
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)

    df = load_csv(args.csv, tz=args.tz, source_tz=args.source_tz, timestamp=args.timestamp)
    p = build_params(args)
    trades, m = run_backtest(df, p)
    if trades is None or len(trades) == 0:
        print("No trades for this config -- nothing to simulate.")
        return

    pnl = trades["net"].to_numpy(dtype=float)
    n = len(pnl)
    # trading-day span -> trades per year
    dates = pd.to_datetime(trades["date"])
    span_years = max((dates.max() - dates.min()).days / 365.25, 1e-9)
    trades_per_year = n / span_years

    print("=" * 78)
    print(f"CONFIG: {args.instrument}  OR{args.or_minutes}m  off{args.offset_ticks}  "
          f"{args.direction}  bias={args.bias}  width<={args.max_or_points:.0f}  "
          f"regime={args.regime}  target={args.target}  ({args.contracts} contract)")
    print("=" * 78)
    print(f"Historical (the realized path): {n} trades over {span_years:.1f} yr "
          f"(~{trades_per_year:.0f}/yr)")
    print(f"  net ${m['net']:,.0f}   PF {m['profit_factor']:.2f}   "
          f"win {m['win_rate']:.1f}%   maxDD(EOD) ${m['max_drawdown']:,.0f}   "
          f"worst trade ${m['worst']:,.0f}")
    print(f"\nMonte Carlo: {args.paths:,} paths, mode={args.mode}"
          + (f" (block={args.block})" if args.mode == "block" else "")
          + f", seed={args.seed}")

    # ---- 1-year outcome distribution ----
    yr_n = int(round(trades_per_year))
    nets_y, dds_y = simulate_outcome_paths(pnl, yr_n, args.paths, args.mode, args.block, rng)
    print("\n" + "-" * 78)
    print(f"ANNUAL OUTCOME ({yr_n} trades/path, per 1 contract):")
    print(f"  net P&L     5th ${pct(nets_y,5):>8,.0f}   median ${pct(nets_y,50):>8,.0f}"
          f"   95th ${pct(nets_y,95):>8,.0f}")
    print(f"  max EOD DD  median ${pct(dds_y,50):>8,.0f}   95th ${pct(dds_y,5):>8,.0f}"
          f"   99th ${pct(dds_y,1):>8,.0f}   worst ${dds_y.min():>8,.0f}")
    print(f"  P(losing year) = {float((nets_y < 0).mean())*100:.1f}%")

    # ---- full-history outcome distribution ----
    nets_f, dds_f = simulate_outcome_paths(pnl, n, args.paths, args.mode, args.block, rng)
    print("\n" + "-" * 78)
    print(f"FULL-HORIZON OUTCOME ({n} trades/path = ~{span_years:.0f}yr, per 1 contract):")
    print(f"  net P&L     5th ${pct(nets_f,5):>8,.0f}   median ${pct(nets_f,50):>9,.0f}"
          f"   95th ${pct(nets_f,95):>9,.0f}")
    print(f"  max EOD DD  median ${pct(dds_f,50):>8,.0f}   95th ${pct(dds_f,5):>8,.0f}"
          f"   99th ${pct(dds_f,1):>8,.0f}   worst ${dds_f.min():>8,.0f}")

    # ---- prop eval race, both accounts, scaled by # micros you'd actually run ----
    print("\n" + "-" * 78)
    print(f"PROP EVAL RACE  (EOD trailing drawdown that locks at start; "
          f"up to {args.max_eval_days} trading days)")
    print("  PASS/BLOW/TIMEOUT = hit profit target / breach loss limit / ran out of days")
    print("  strictBLOW = same but with a never-locking (always-trailing) DD -- the worst case\n")
    for label, tgt, lim, max_micros in ACCOUNTS:
        for micros in (1, 2):
            scaled = pnl * micros
            pp, pb, pt, med = simulate_eval(scaled, tgt, lim, args.max_eval_days,
                                            args.paths, args.mode, args.block, rng, lock=True)
            _, sb, _, _ = simulate_eval(scaled, tgt, lim, args.max_eval_days,
                                        args.paths, args.mode, args.block, rng, lock=False)
            med_s = f"{med:.0f}d" if med == med else "n/a"
            print(f"  {label}  {micros} micro  tgt ${tgt:,.0f}/lim ${lim:,.0f}: "
                  f"PASS {pp*100:5.1f}%  BLOW {pb*100:5.1f}%  TIMEOUT {pt*100:5.1f}%"
                  f"  (median pass {med_s}; strictBLOW {sb*100:.1f}%)")
    print("=" * 78)
    print("Read: BLOW% is the chance the account dies before passing. A config is "
          "prop-viable only if BLOW% is low AND PASS% dominates.")


if __name__ == "__main__":
    main()
