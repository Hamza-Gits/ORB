"""
Deep dive vs NinjaTrader Run #3 (timezone now = Eastern Time US&Canada).
NT result: 60 trades / 10.0% win / -$2,712.50 on MNQ SEP26, Jan1-Jun23 2026.

Goal: day-by-day reconcile Python (clean continuous) vs NT (SEP26 single contract).
We expose: per-day OR levels, prior-day ATR & ADX, exit reasons, and a date-keyed
diff so we can see WHERE the two engines disagree (same side / opp side / py-only / nt-only).
"""
import numpy as np
import pandas as pd
from orb_strategy import (Params, load_csv, prepare_days, run_prepared,
                          _atr, _adx)

WIN_LO = pd.Timestamp("2026-01-01", tz="America/New_York")
WIN_HI = pd.Timestamp("2026-06-23 23:59", tz="America/New_York")

df = load_csv("MNQ_full_1min.csv", tz="America/New_York", source_tz=None, timestamp="open")
print(f"Loaded {len(df):,} bars  {df.index.min()} -> {df.index.max()}\n")

p = Params(
    instrument="MNQ", or_start="09:30", or_minutes=15, exit_time="15:55",
    offset_ticks=2, direction="both", max_trades=1, max_or_points=130,
    bias="vwap_slope", regime="adx", regime_adx_min=20, atr_period=14,
    target_mode="atr", target_atr_mult=1.5, commission_rt=1.24,
    slippage_ticks=1, contracts=1,
)

days = prepare_days(df)
trades, m = run_prepared(days, p)

# ---- daily indicator arrays, same construction as the engine ----
d_high = np.array([float(d["high"].max()) for d in days])
d_low  = np.array([float(d["low"].min())  for d in days])
d_close= np.array([float(d["close"][-1])  for d in days])
atr_arr = _atr(d_high, d_low, d_close, p.atr_period)
adx_arr = _adx(d_high, d_low, d_close, 14)
day_dates = [d["date"] for d in days]
date_to_i = {d: i for i, d in enumerate(day_dates)}

et = pd.to_datetime(trades["entry_time"])
sub = trades[(et >= WIN_LO) & (et <= WIN_HI)].copy()
sub["d"] = pd.to_datetime(sub["entry_time"]).dt.date

def fdollar(x): return f"${x:,.0f}"

print("="*78)
print("PYTHON CHAMPION  (clean continuous MNQ)")
print("="*78)
print(f"Full 2019-2026 : {len(trades)} trades  net ${trades['net'].sum():,.0f}  "
      f"win {len(trades[trades.net>0])/len(trades)*100:.1f}%")
print(f"2026 window     : {len(sub)} trades  net ${sub['net'].sum():,.0f}  "
      f"win {len(sub[sub.net>0])/len(sub)*100:.1f}%")
print("\nExit-reason mix (2026 window):")
print(sub["reason"].value_counts().to_string())
print("\nWins by exit reason:")
print(sub[sub.net>0]["reason"].value_counts().to_string())

# prior-day ATR magnitude across the window (drives the 1.5x target distance)
win_idx = [date_to_i[d] for d in [dd.date() for dd in pd.date_range('2026-01-02','2026-06-23')]
           if d in date_to_i]
atr_prev = [atr_arr[i-1] for i in win_idx if i>=1 and not np.isnan(atr_arr[i-1])]
print(f"\nPrior-day ATR(14) over window: min {min(atr_prev):.0f}  "
      f"med {np.median(atr_prev):.0f}  max {max(atr_prev):.0f} pts")
print(f"  -> 1.5x ATR target distance: ~{1.5*np.median(atr_prev):.0f} pts "
      f"(={1.5*np.median(atr_prev)*2:.0f} $ if hit)")

# ---- detailed python trade log ----
print("\n" + "="*78)
print("PYTHON 2026 TRADES (the days it actually traded)")
print("="*78)
print(f"{'date':<12}{'side':<7}{'entry':<7}{'reason':<8}{'net':>8}   "
      f"{'ORlo':>8}{'ORhi':>8}{'rng':>6}{'ADXp':>7}{'ATRp':>7}")
py_by_date = {}
for _, r in sub.iterrows():
    i = date_to_i.get(r["d"])
    adxp = adx_arr[i-1] if i and i>=1 else float('nan')
    atrp = atr_arr[i-1] if i and i>=1 else float('nan')
    etime = pd.to_datetime(r["entry_time"]).strftime("%H:%M")
    py_by_date[r["d"]] = r["direction"]
    print(f"{str(r['d']):<12}{r['direction']:<7}{etime:<7}{r['reason']:<8}"
          f"{r['net']:>8.0f}   {r['or_low']:>8.0f}{r['or_high']:>8.0f}"
          f"{r['range_pts']:>6.0f}{adxp:>7.1f}{atrp:>7.0f}")

# ---- parse NT trades ----
nt_path = r"C:\Users\hamza\Downloads\Ai projects\5 Min ORB\Back Test Results\3\NinjaTrader Grid 2026-06-2408-59 PM.csv"
nt = pd.read_csv(nt_path)
nt = nt[nt["Trade number"].notna()].copy()
nt["d"] = pd.to_datetime(nt["Entry time"], dayfirst=True).dt.date
nt["side"] = nt["Market pos."].str.lower()
nt["pnl"] = nt["Profit"].str.replace("[$,]","",regex=True).astype(float)
nt["etime"] = pd.to_datetime(nt["Entry time"], dayfirst=True).dt.strftime("%H:%M")
nt_by_date = dict(zip(nt["d"], nt["side"]))

print("\n" + "="*78)
print(f"NINJATRADER 2026: {len(nt)} trades  net ${nt['pnl'].sum():,.0f}  "
      f"win {len(nt[nt.pnl>0])/len(nt)*100:.1f}%")
print("="*78)
print("NT exit-name mix:")
print(nt["Exit name"].value_counts().to_string())

# ---- date-keyed diff ----
all_dates = sorted(set(py_by_date) | set(nt_by_date))
both_same = both_opp = py_only = nt_only = 0
print("\n" + "="*78)
print("DAY-BY-DAY DIFF  (only days where at least one engine traded)")
print("="*78)
print(f"{'date':<12}{'PY':<10}{'NT':<10}{'verdict':<14}{'NT_pnl':>8}")
for d in all_dates:
    pys = py_by_date.get(d, "-")
    nts = nt_by_date.get(d, "-")
    ntp = nt[nt.d==d]["pnl"].sum() if d in nt_by_date else 0.0
    if pys != "-" and nts != "-":
        if pys == nts:
            v = "SAME side"; both_same += 1
        else:
            v = "OPPOSITE"; both_opp += 1
    elif pys != "-":
        v = "PY only"; py_only += 1
    else:
        v = "NT only"; nt_only += 1
    print(f"{str(d):<12}{pys:<10}{nts:<10}{v:<14}{ntp:>8.0f}")

print("\n" + "="*78)
print("RECONCILIATION SUMMARY")
print("="*78)
print(f"  Days both traded, SAME side : {both_same}")
print(f"  Days both traded, OPP side  : {both_opp}")
print(f"  Days PYTHON traded, NT did NOT: {py_only}")
print(f"  Days NT traded, PYTHON did NOT: {nt_only}")
nt_extra_pnl = sum(nt[nt.d==d]["pnl"].sum() for d in nt_by_date if d not in py_by_date)
print(f"\n  P&L on NT's extra days (PY skipped): ${nt_extra_pnl:,.0f}")
print(f"  -> these are days Python's ADX/VWAP filter REJECTED but NT traded anyway")
