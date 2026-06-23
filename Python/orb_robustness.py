"""
orb_robustness.py
=================
"Beat the idea to death." Split the history into N contiguous segments, run the
FULL parameter grid on each segment independently, and find the parameter sets
that make money in EVERY segment -- not just in the one period you optimized on.

A real edge shows up across all segments. A curve-fit shows up in one and dies
in the others. This is a much stronger test than a single train/test split.

    python orb_robustness.py --csv MNQ_1min.csv --instrument MNQ --segments 2
    python orb_robustness.py --csv MNQ_1min.csv --instrument MNQ --segments 4

Output: <out> CSV with each config's net P&L in every segment, ranked by its
WORST segment (so the top of the list = most consistent across time).
"""

import argparse
import itertools
from dataclasses import replace

import numpy as np
import pandas as pd

from orb_strategy import INSTRUMENTS, Params, load_csv, prepare_days, run_prepared
from orb_optimize import GRID


def segment_days(days, n):
    days = sorted(days, key=lambda d: d["date"])
    return [[days[i] for i in idx] for idx in np.array_split(np.arange(len(days)), n)]


def grid_on(days, base, grid):
    keys = list(grid.keys())
    rows = []
    for combo in itertools.product(*[grid[k] for k in keys]):
        kw = dict(zip(keys, combo))
        _, m = run_prepared(days, replace(base, **kw))
        rows.append({**kw, "net": m["net"], "pf": m["profit_factor"], "tr": m["trades"]})
    return pd.DataFrame(rows).set_index(keys)


def main():
    ap = argparse.ArgumentParser(description="Multi-segment robustness test for the ORB grid")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--instrument", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--segments", type=int, default=2)
    ap.add_argument("--min-trades", type=int, default=40, dest="min_trades",
                    help="minimum trades PER SEGMENT for a config to qualify")
    ap.add_argument("--commission-rt", type=float, default=1.24, dest="commission_rt")
    ap.add_argument("--slippage-ticks", type=int, default=1, dest="slippage_ticks")
    ap.add_argument("--tz", default="America/New_York")
    ap.add_argument("--source-tz", default=None, dest="source_tz")
    ap.add_argument("--timestamp", default="open", choices=["open", "close"])
    ap.add_argument("--out", default="orb_robustness.csv")
    args = ap.parse_args()

    df = load_csv(args.csv, tz=args.tz, source_tz=args.source_tz, timestamp=args.timestamp)
    days = prepare_days(df)
    base = Params(instrument=args.instrument, commission_rt=args.commission_rt,
                  slippage_ticks=args.slippage_ticks)
    keys = list(GRID.keys())

    segs = segment_days(days, args.segments)
    merged = None
    netcols, trcols = [], []
    for i, s in enumerate(segs, 1):
        print(f"Segment {i}: {s[0]['date']} -> {s[-1]['date']}  ({len(s)} days)  running {1}x full grid...")
        t = grid_on(s, base, GRID)
        merged = t[["net", "pf", "tr"]].rename(columns={"net": f"net{i}", "pf": f"pf{i}", "tr": f"tr{i}"}) \
            if merged is None else merged.join(
                t[["net", "pf", "tr"]].rename(columns={"net": f"net{i}", "pf": f"pf{i}", "tr": f"tr{i}"}))
        netcols.append(f"net{i}")
        trcols.append(f"tr{i}")

    merged["min_net"] = merged[netcols].min(axis=1)
    merged["sum_net"] = merged[netcols].sum(axis=1)
    merged["n_pos"] = (merged[netcols] > 0).sum(axis=1)
    enough = (merged[trcols] >= args.min_trades).all(axis=1)

    total = len(merged)
    all_pos = int((merged["n_pos"] == len(segs)).sum())
    qual = merged[enough].copy()
    print(f"\nConfigs profitable in ALL {len(segs)} segments: {all_pos} / {total} "
          f"({100*all_pos/total:.0f}%)")
    print(f"Configs meeting the >= {args.min_trades} trades/segment filter: {len(qual)} / {total}")

    robust = qual.sort_values("min_net", ascending=False).head(15)
    show = netcols + ["min_net", "sum_net", "n_pos"]
    with pd.option_context("display.width", 180, "display.max_columns", None):
        print("\nMost ROBUST configs (ranked by WORST-segment net -- top = most consistent):\n")
        print(robust[show].reset_index().to_string(index=False))

    merged.reset_index().to_csv(args.out, index=False)
    print(f"\nSaved full segment table -> {args.out}")
    print("\nVerdict guide: if 'min_net' is negative for nearly every config, the strategy")
    print("has no time-stable edge at these settings -- the in-sample winners were curve-fit.")


if __name__ == "__main__":
    main()
