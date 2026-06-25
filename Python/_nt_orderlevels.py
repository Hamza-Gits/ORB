"""
Extract per-trade price geometry from NT's ORDERS export and compare to Python
on the SAME days. Tests the hypothesis: SEP26 (illiquid back month) has inflated
daily volatility -> targets placed too far AND ADX filter fooled by noise.

From the orders file, per trade we recover:
  entry trigger  = Stop of the ORlong/ORshort order
  stop level     = Stop of the 'Stop loss' order   -> OR width = |trigger - stop| - offsets
  target level   = Limit of the 'Profit target' order -> target dist = |target-trigger|
                   implied daily ATR = target dist / 1.5
"""
import numpy as np
import pandas as pd
from orb_strategy import Params, load_csv, prepare_days, run_prepared, _atr, _adx

orders_path = r"C:\Users\hamza\Downloads\Ai projects\5 Min ORB\Back Test Results\3\NinjaTrader Grid 2026-062408-59 PM.csv"
o = pd.read_csv(orders_path)
o.columns = [c.strip() for c in o.columns]
o["t"] = pd.to_datetime(o["Time"], dayfirst=True)
o["d"] = o["t"].dt.date

# group orders by day; each day has ORlong/ORshort entry, Stop loss, Profit target
rows = []
for d, g in o.groupby("d"):
    entry = g[g["Name"].isin(["ORlong","ORshort"])]
    sl    = g[g["Name"]=="Stop loss"]
    tgt   = g[g["Name"]=="Profit target"]
    if entry.empty:
        continue
    e = entry.iloc[0]
    side = "long" if e["Name"]=="ORlong" else "short"
    trig = float(e["Stop"])
    stop = float(sl.iloc[0]["Stop"]) if not sl.empty else np.nan
    tlim = float(tgt.iloc[0]["Limit"]) if not tgt.empty else np.nan
    or_width = abs(trig - stop) if not np.isnan(stop) else np.nan
    tgt_dist = abs(tlim - trig) if not np.isnan(tlim) else np.nan
    impl_atr = tgt_dist / 1.5 if not np.isnan(tgt_dist) else np.nan
    rows.append(dict(d=d, side=side, trig=trig, stop=stop, tgt=tlim,
                     or_width=or_width, tgt_dist=tgt_dist, impl_atr=impl_atr))
nt = pd.DataFrame(rows).set_index("d")

# ---- python side ----
df = load_csv("MNQ_full_1min.csv", tz="America/New_York", source_tz=None, timestamp="open")
p = Params(instrument="MNQ", or_start="09:30", or_minutes=15, exit_time="15:55",
           offset_ticks=2, direction="both", max_trades=1, max_or_points=130,
           bias="vwap_slope", regime="adx", regime_adx_min=20, atr_period=14,
           target_mode="atr", target_atr_mult=1.5, commission_rt=1.24,
           slippage_ticks=1, contracts=1)
days = prepare_days(df)
trades, _ = run_prepared(days, p)
d_high=np.array([float(x["high"].max()) for x in days]); d_low=np.array([float(x["low"].min()) for x in days])
d_close=np.array([float(x["close"][-1]) for x in days])
atr_arr=_atr(d_high,d_low,d_close,14); adx_arr=_adx(d_high,d_low,d_close,14)
date_to_i={x["date"]:i for i,x in enumerate(days)}
et=pd.to_datetime(trades["entry_time"]); trades["d"]=et.dt.date
py=trades.set_index("d")

print("="*96)
print("NT IMPLIED DAILY ATR (target_dist / 1.5)  across all 60 NT trades")
print("="*96)
print(f"  NT implied ATR: min {nt['impl_atr'].min():.0f}  med {nt['impl_atr'].median():.0f}  "
      f"max {nt['impl_atr'].max():.0f} pts   (n={nt['impl_atr'].notna().sum()})")
print(f"  NT OR width   : min {nt['or_width'].min():.0f}  med {nt['or_width'].median():.0f}  "
      f"max {nt['or_width'].max():.0f} pts")
# python ATR over same window
win_i=[date_to_i[d] for d in date_to_i if pd.Timestamp(d)>=pd.Timestamp('2026-01-02') and pd.Timestamp(d)<=pd.Timestamp('2026-06-23')]
pa=[atr_arr[i-1] for i in win_i if i>=1 and not np.isnan(atr_arr[i-1])]
print(f"\n  PY daily ATR  : min {min(pa):.0f}  med {np.median(pa):.0f}  max {max(pa):.0f} pts")

print("\n" + "="*96)
print("SAME-DAY GEOMETRY  (days BOTH engines traded) -- price level, OR width, implied ATR")
print("="*96)
print(f"{'date':<12}{'PYside':<7}{'NTside':<7}{'PY_ORhi':>9}{'NT_trig':>9}{'basis':>8}"
      f"{'PY_rng':>8}{'NT_rng':>8}{'PY_ATR':>8}{'NT_ATR':>8}")
shared=sorted(set(py.index)&set(nt.index))
basis_list=[]; pyrng=[]; ntrng=[]; pyatr=[]; ntatr=[]
for d in shared:
    pr=py.loc[[d]].iloc[0]; nr=nt.loc[[d]].iloc[0]
    i=date_to_i.get(d); a=atr_arr[i-1] if i and i>=1 else np.nan
    basis = nr["trig"] - (pr["or_high"] if pr["direction"]=="long" else pr["or_low"])
    basis_list.append(basis); pyrng.append(pr["range_pts"]); ntrng.append(nr["or_width"])
    pyatr.append(a); ntatr.append(nr["impl_atr"])
    print(f"{str(d):<12}{pr['direction']:<7}{nr['side']:<7}{pr['or_high']:>9.0f}{nr['trig']:>9.0f}"
          f"{basis:>8.0f}{pr['range_pts']:>8.0f}{nr['or_width']:>8.0f}{a:>8.0f}{nr['impl_atr']:>8.0f}")

print("\n" + "="*96)
print("AVERAGES on shared days")
print("="*96)
print(f"  Mean basis (NT level - PY level)   : {np.nanmean(basis_list):>7.0f} pts")
print(f"  Mean OR width   PY {np.nanmean(pyrng):>6.0f}  vs  NT {np.nanmean(ntrng):>6.0f} pts")
print(f"  Mean daily ATR  PY {np.nanmean(pyatr):>6.0f}  vs  NT {np.nanmean(ntatr):>6.0f} pts")
print(f"\n  NT OR width / PY OR width ratio : {np.nanmean(ntrng)/np.nanmean(pyrng):.2f}x")
print(f"  NT ATR / PY ATR ratio          : {np.nanmean(ntatr)/np.nanmean(pyatr):.2f}x")
