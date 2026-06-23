"""
make_sample_data.py
===================
Generate a SYNTHETIC 1-minute RTH CSV so you can test the whole pipeline
before you have real market data. The output matches the format the loader
expects: comma-separated, header row, start-of-bar timestamps in ET.

    python make_sample_data.py --instrument MNQ --days 120 --out sample_MNQ_1min.csv

IMPORTANT: this is random data. Use it only to confirm the scripts run and the
numbers print. Any "profit" on it is meaningless -- replace it with real MNQ /
MES history before drawing any conclusion (see the README for where to get it).
"""

import argparse
from datetime import datetime, timedelta, time

import numpy as np
import pandas as pd

START_PRICE = {"MNQ": 18000.0, "NQ": 18000.0, "MES": 5000.0, "ES": 5000.0}
TICK = 0.25


def round_tick(x):
    return round(round(x / TICK) * TICK, 2)


def main():
    ap = argparse.ArgumentParser(description="Generate synthetic 1-min RTH data")
    ap.add_argument("--instrument", default="MNQ", choices=list(START_PRICE))
    ap.add_argument("--days", type=int, default=120, help="number of trading days")
    ap.add_argument("--start", default="2024-01-01", help="start date YYYY-MM-DD")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="sample_MNQ_1min.csv")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    price = START_PRICE[args.instrument]
    step_sd = price * 0.00025          # per sub-step volatility

    date = datetime.strptime(args.start, "%Y-%m-%d").date()
    rows = []
    sessions = 0
    while sessions < args.days:
        if date.weekday() < 5:                       # Mon-Fri only
            for minute in range(390):                # 09:30 .. 15:59 = 390 bars
                ts = datetime.combine(date, time(9, 30)) + timedelta(minutes=minute)
                vol = step_sd * (2.0 if minute < 30 else 1.0)   # busier at the open
                o = price
                path = o + np.cumsum(rng.normal(0, vol, 4))     # 4 ticks inside the bar
                c = float(path[-1])
                hi = max(o, float(path.max()))
                lo = min(o, float(path.min()))
                rows.append((ts.strftime("%Y-%m-%d %H:%M:%S"),
                             round_tick(o), round_tick(hi), round_tick(lo), round_tick(c),
                             int(rng.integers(200, 3000))))
                price = c
            price += float(rng.normal(0, step_sd * 6))          # overnight gap
            sessions += 1
        date += timedelta(days=1)

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df.to_csv(args.out, index=False)
    print(f"Wrote {len(df):,} bars over {args.days} sessions -> {args.out}")
    print("This is random data for a smoke-test only. Swap in real history before trusting results.")


if __name__ == "__main__":
    main()
