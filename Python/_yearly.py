import pandas as pd
from dataclasses import replace
from orb_strategy import Params, load_csv, run_backtest

df = load_csv("MNQ_full_1min.csv", tz="America/New_York")
base = Params(instrument="MNQ", commission_rt=1.24, slippage_ticks=1)

CONFIGS = [
    ("RECOMMENDED  15m/off2/vwap_slope/w130/ADX/ATR1.5  (prop-fit, 50K)",
     dict(or_minutes=15, offset_ticks=2, direction="both", bias="vwap_slope",
          max_or_points=130, regime="adx", target_mode="atr", target_atr_mult=1.5)),
    ("HIGH-NET     15m/off2/vwap_slope/w130/none/ATR2.5  (bigger acct)",
     dict(or_minutes=15, offset_ticks=2, direction="both", bias="vwap_slope",
          max_or_points=130, regime="none", target_mode="atr", target_atr_mult=2.5)),
]

for label, ov in CONFIGS:
    p = replace(base, **ov)
    tr, m = run_backtest(df, p)
    tr["year"] = pd.to_datetime(tr["date"]).dt.year
    g = tr.groupby("year").agg(trades=("net", "size"), net=("net", "sum"),
                               wins=("net", lambda x: (x > 0).sum()))
    g["win%"] = (g["wins"] / g["trades"] * 100).round(1)
    g["net"] = g["net"].round(0).astype(int)
    print("\n=== " + label + " ===")
    print("TOTAL: {} trades  net ${:,.0f}  PF {:.2f}  win {:.1f}%  maxDD ${:,.0f}".format(
        len(tr), m["net"], m["profit_factor"], m["win_rate"], m["max_drawdown"]))
    print(g[["trades", "win%", "net"]].to_string())
