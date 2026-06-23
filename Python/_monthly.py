import numpy as np
import pandas as pd
from dataclasses import replace
from orb_strategy import Params, load_csv, run_backtest

df = load_csv("MNQ_full_1min.csv", tz="America/New_York")
base = Params(instrument="MNQ", commission_rt=1.24, slippage_ticks=1)
p = replace(base, or_minutes=15, offset_ticks=2, direction="both", bias="vwap_slope",
            max_or_points=130, regime="adx", target_mode="atr", target_atr_mult=1.5)

tr, m = run_backtest(df, p)
tr["dt"] = pd.to_datetime(tr["date"])
tr["year"] = tr["dt"].dt.year
tr["mon"] = tr["dt"].dt.month

# month x year matrix of net $ (per 1 micro)
piv = tr.pivot_table(index="year", columns="mon", values="net", aggfunc="sum").round(0)
piv = piv.reindex(columns=range(1, 13))
months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
piv.columns = months
piv["YEAR"] = piv.sum(axis=1).round(0)

pd.set_option("display.width", 200); pd.set_option("display.max_columns", None)
print("MONTHLY NET P&L ($, per 1 micro)  --  15m/off2/vwap_slope/w130/ADX/ATR1.5")
print("="*100)
print(piv.fillna(0).astype(int).to_string())
print()

# monthly series stats
monthly = tr.groupby([tr["dt"].dt.to_period("M")])["net"].sum()
n = len(monthly)
pos = (monthly > 0).sum()
print("MONTHLY STATISTICS (per 1 micro)")
print("-"*60)
print(f"  Months traded        {n}")
print(f"  Positive months      {pos}  ({pos/n*100:.0f}%)")
print(f"  Negative months      {n-pos}  ({(n-pos)/n*100:.0f}%)")
print(f"  Average month        ${monthly.mean():,.0f}")
print(f"  Median month         ${monthly.median():,.0f}")
print(f"  Std dev (month)       ${monthly.std():,.0f}")
print(f"  Best month           ${monthly.max():,.0f}  ({monthly.idxmax()})")
print(f"  Worst month          ${monthly.min():,.0f}  ({monthly.idxmin()})")
print(f"  Worst 3-month stretch ${monthly.rolling(3).sum().min():,.0f}")
print()
# distribution buckets
print("  Monthly P&L distribution:")
buckets = [(-9999,-200),(-200,0),(0,200),(200,400),(400,600),(600,9999)]
labels = ["< -$200","-$200..0","$0..200","$200..400","$400..600","> $600"]
for (lo,hi),lab in zip(buckets,labels):
    c = ((monthly>lo)&(monthly<=hi)).sum()
    bar = "#"*c
    print(f"   {lab:>12s} : {c:2d}  {bar}")
