"""
orb_optimize.py
===============
Grid-search the 5-minute ORB parameters and rank them, with an optional
walk-forward (train/test) split so you don't fool yourself with curve-fitting.

Examples
--------
    # full grid, rank by net P&L, need >= 30 trades to qualify
    python orb_optimize.py --csv sample_MNQ_1min.csv --instrument MNQ

    # rank by profit factor and split into in-sample / out-of-sample at a date
    python orb_optimize.py --csv MES_1min.csv --instrument MES \
                           --objective profit_factor --split 2024-01-01

What it does
------------
    1. Runs every combination of the parameter grid below.
    2. Saves the full results table to <out>_grid.csv.
    3. Prints the top configurations (filtered by a minimum trade count).
    4. Draws a heatmap of RR x OR-length (direction=both, offset=0).
    5. If --split is given: finds the best params on the TRAIN period, then
       reports how they actually performed on the unseen TEST period.

Read the warning at the bottom of the run. A setup that only looks good in-
sample, or only with one exact parameter, is noise -- not an edge.
"""

import argparse
import itertools
from dataclasses import replace

import pandas as pd

from orb_strategy import (INSTRUMENTS, Params, load_csv, run_backtest,
                          prepare_days, run_prepared)


# --- the search space. Edit these lists to widen / narrow the search. -------
# This is a BROAD sweep (7 x 8 x 6 x 3 = 1008 combinations). More parameters
# means more chances to curve-fit, so judge the results by the robustness rules
# the script prints at the end -- look for a PLATEAU, not a single lucky cell.
GRID = {
    "rr":           [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0],   # reward:risk
    "or_minutes":   [1, 2, 3, 5, 10, 15, 30, 60],            # opening-range length
    "offset_ticks": [0, 1, 2, 3, 4, 8],                      # breakout confirmation
    "direction":    ["both", "long", "short"],               # which way we trade
}

REPORT_COLS = ["trades", "win_rate", "net", "profit_factor",
               "expectancy", "avg_R", "max_drawdown", "sharpe"]


def run_grid(df, base: Params, grid=GRID) -> pd.DataFrame:
    # prepare_days() splits the data once; every combo then reuses it (~10x faster).
    days = prepare_days(df)
    keys = list(grid.keys())
    rows = []
    for combo in itertools.product(*[grid[k] for k in keys]):
        kw = dict(zip(keys, combo))
        p = replace(base, **kw)
        _, m = run_prepared(days, p)
        rows.append({**kw, **{c: m[c] for c in REPORT_COLS}})
    return pd.DataFrame(rows)


def show_top(res: pd.DataFrame, objective: str, min_trades: int, n=15):
    ok = res[res["trades"] >= min_trades].copy()
    if len(ok) == 0:
        print(f"\n(no configurations reached {min_trades} trades -- lower --min-trades)")
        return res.sort_values(objective, ascending=False, na_position="last").head(n)
    # na_position="last": nan profit_factor (zero-loss cells) sort after finite values
    ok = ok.sort_values(objective, ascending=False, na_position="last")
    with pd.option_context("display.width", 160, "display.max_columns", None):
        print(f"\nTop {n} by {objective} (>= {min_trades} trades):\n")
        print(ok.head(n).to_string(index=False))
    return ok


def heatmap(res: pd.DataFrame, out_prefix: str, instrument: str):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib not installed -> skipped heatmap)")
        return

    sub = res[(res["direction"] == "both") & (res["offset_ticks"] == 0)]
    if len(sub) == 0:
        return
    pivot = sub.pivot_table(index="or_minutes", columns="rr", values="net")
    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(pivot.values, aspect="auto", origin="lower", cmap="RdYlGn")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel("Reward:Risk")
    ax.set_ylabel("OR length (min)")
    ax.set_title(f"{instrument} net P&L  (direction=both, offset=0)")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.values[i, j]
            if pd.notna(v):
                ax.text(j, i, f"{v:,.0f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="net $")
    fig.tight_layout()
    png = f"{out_prefix}_heatmap.png"
    fig.savefig(png, dpi=110)
    print(f"\nSaved heatmap -> {png}")


def main():
    ap = argparse.ArgumentParser(description="5-minute ORB parameter optimizer")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--instrument", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--objective", default="net",
                    choices=["net", "profit_factor", "expectancy", "sharpe", "avg_R"])
    ap.add_argument("--min-trades", type=int, default=30, dest="min_trades")
    ap.add_argument("--split", default=None,
                    help="walk-forward cutoff date YYYY-MM-DD (train < date <= test)")
    ap.add_argument("--commission-rt", type=float, default=1.24, dest="commission_rt")
    ap.add_argument("--slippage-ticks", type=int, default=1, dest="slippage_ticks")
    ap.add_argument("--tz", default="America/New_York")
    ap.add_argument("--source-tz", default=None, dest="source_tz",
                    help="timezone the file is actually in (e.g. UTC for raw NinjaTrader exports)")
    ap.add_argument("--timestamp", default="open", choices=["open", "close"])
    ap.add_argument("--out", default="orb")
    args = ap.parse_args()

    df = load_csv(args.csv, tz=args.tz, source_tz=args.source_tz, timestamp=args.timestamp)
    print(f"Loaded {len(df):,} bars  {df.index.min()}  ->  {df.index.max()}")

    base = Params(instrument=args.instrument, commission_rt=args.commission_rt,
                  slippage_ticks=args.slippage_ticks)

    n_combos = 1
    for v in GRID.values():
        n_combos *= len(v)
    print(f"Searching {n_combos} combinations...")

    if not args.split:
        res = run_grid(df, base)
        res.to_csv(f"{args.out}_grid.csv", index=False)
        print(f"Saved full grid -> {args.out}_grid.csv")
        show_top(res, args.objective, args.min_trades)
        heatmap(res, args.out, args.instrument)
    else:
        cutoff = pd.Timestamp(args.split, tz=args.tz)
        train, test = df[df.index < cutoff], df[df.index >= cutoff]
        print(f"\nWALK-FORWARD  train: {len(train):,} bars (< {args.split})   "
              f"test: {len(test):,} bars (>= {args.split})")

        train_res = run_grid(train, base)
        train_res.to_csv(f"{args.out}_train_grid.csv", index=False)
        best = show_top(train_res, args.objective, args.min_trades, n=10)

        if best is not None and len(best):
            row = best.iloc[0]
            chosen = replace(base, rr=float(row["rr"]), or_minutes=int(row["or_minutes"]),
                             offset_ticks=int(row["offset_ticks"]), direction=str(row["direction"]))
            _, m_in = run_backtest(train, chosen)
            _, m_out = run_backtest(test, chosen)
            print("\n--- Best TRAIN params applied out-of-sample ---")
            print(f"  params : RR {chosen.rr}  OR {chosen.or_minutes}m  "
                  f"offset {chosen.offset_ticks}t  dir {chosen.direction}")
            print(f"  TRAIN  : net ${m_in['net']:,.0f}  PF {m_in['profit_factor']:.2f}  "
                  f"trades {m_in['trades']:.0f}")
            print(f"  TEST   : net ${m_out['net']:,.0f}  PF {m_out['profit_factor']:.2f}  "
                  f"trades {m_out['trades']:.0f}")
            if m_out["net"] <= 0 or m_out["profit_factor"] < 1.0:
                print("  >> The edge did NOT survive out-of-sample. Likely curve-fit.")
            else:
                print("  >> Edge held up out-of-sample. Promising -- keep stress-testing.")

    print("\nReminder: trust a PLATEAU of good neighbouring parameters, not a single")
    print("lucky cell. If only one exact combo works, it is noise, not an edge.")


if __name__ == "__main__":
    main()
