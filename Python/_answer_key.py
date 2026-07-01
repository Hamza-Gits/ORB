"""
Answer key: run the champion and dump every trade with the same fields the
manual tester uses (date, side=VWAP-allowed side, OR width, prior-day ADX,
exit reason, points, net, running equity). Lets the user verify manual reads
against the real engine instead of grinding every day by hand.
"""
import numpy as np, pandas as pd
from orb_strategy import Params, load_csv, prepare_days, run_prepared, _adx

df = load_csv("MNQ_full_1min.csv", tz="America/New_York", source_tz=None, timestamp="open")
p = Params(instrument="MNQ", or_start="09:30", or_minutes=15, exit_time="15:55",
           offset_ticks=2, direction="both", max_trades=1, max_or_points=130,
           bias="vwap_slope", regime="adx", regime_adx_min=20, atr_period=14,
           target_mode="atr", target_atr_mult=1.5, commission_rt=1.24,
           slippage_ticks=1, contracts=1)
days = prepare_days(df)
trades, m = run_prepared(days, p)

d_high=np.array([float(d["high"].max()) for d in days]); d_low=np.array([float(d["low"].min()) for d in days])
d_close=np.array([float(d["close"][-1]) for d in days]); adx=_adx(d_high,d_low,d_close,14)
i_of={d["date"]:i for i,d in enumerate(days)}

t=trades.copy()
t["d"]=pd.to_datetime(t["entry_time"]).dt.date
t["etime"]=pd.to_datetime(t["entry_time"]).dt.strftime("%H:%M")
t["adx_prev"]=[adx[i_of[d]-1] if i_of[d]>=1 else np.nan for d in t["d"]]
t["exit"]=t["reason"].map({"stop":"stopped","time":"flat 15:55"}).fillna(t["reason"])
t["cum"]=t["net"].cumsum()

# full-history CSV (the complete answer key)
out=t[["d","direction","range_pts","adx_prev","etime","exit","points","net","cum"]].copy()
out.columns=["date","side","or_width","prior_adx","entry_et","exit","points","net","cum_net"]
out=out.round({"or_width":1,"prior_adx":1,"points":1,"net":2,"cum_net":2})
csv_path=r"C:\Users\hamza\Downloads\Ai projects\5 Min ORB\Manual Tester\orb_answer_key.csv"
out.to_csv(csv_path,index=False)

def summ(sub,label):
    n=len(sub); w=(sub.net>0).sum()
    print(f"{label:<22} {n:>3} trades   win {w/n*100:4.1f}%   net ${sub.net.sum():>9,.0f}")

print("="*70)
print("CHAMPION ANSWER KEY  —  every trade, running P&L")
print("="*70)
summ(t,"FULL 2019-2026")
for yr in [2022,2023,2024,2025,2026]:
    s=t[pd.to_datetime(t.entry_time).dt.year==yr]
    if len(s): summ(s,f"  {yr}")
print(f"\nFull CSV written: {csv_path}  ({len(out)} rows)")

# readable recent window to eyeball / spot-check
rec=t[pd.to_datetime(t.entry_time)>=pd.Timestamp("2026-01-01",tz="America/New_York")]
print("\n"+"="*70)
print(f"RECENT WINDOW (2026 YTD) — {len(rec)} trades, spot-check these on your chart")
print("="*70)
print(f"{'date':<12}{'side':<6}{'width':>6}{'ADXp':>6}{'entry':>7}{'exit':>12}{'pts':>7}{'net$':>8}{'cum$':>9}")
for _,r in rec.iterrows():
    print(f"{str(r['d']):<12}{r['direction']:<6}{r['range_pts']:>6.0f}{r['adx_prev']:>6.1f}"
          f"{r['etime']:>7}{r['exit']:>12}{r['points']:>7.1f}{r['net']:>8.0f}{r['cum']:>9.0f}")
