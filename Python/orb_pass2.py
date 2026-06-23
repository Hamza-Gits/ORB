"""
orb_pass2.py
============
Standalone Pass 2 (segment robustness) that reads a saved Pass-1 full grid CSV
(from orb_final.py) instead of recomputing the whole grid. Use this to finish a
robustness pass when Pass 1 already wrote its <out>_fullgrid.csv.

Re-runs every Pass-1 survivor over each time segment, keeps the configs that make
money in EVERY segment, and ranks them by their WORST segment.

    python orb_pass2.py --csv MNQ_full_1min.csv --grid mnq7_all_fullgrid.csv \
        --segments 5 --out mnq7_all
"""

import argparse
import sys
from dataclasses import replace

import pandas as pd

from orb_strategy import INSTRUMENTS, Params, load_csv, prepare_days, run_prepared
from orb_robustness import segment_days
from orb_final import KEYS, _build_params


def main():
    ap = argparse.ArgumentParser(description="Standalone robustness Pass 2 from a saved grid")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--grid", required=True, help="Pass-1 *_fullgrid.csv to read survivors from")
    ap.add_argument("--instrument", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--segments", type=int, default=5)
    ap.add_argument("--min-trades", type=int, default=150, dest="min_trades")
    ap.add_argument("--min-trades-seg", type=int, default=25, dest="min_trades_seg")
    ap.add_argument("--contracts", type=int, default=1)
    ap.add_argument("--commission-rt", type=float, default=1.24, dest="commission_rt")
    ap.add_argument("--slippage-ticks", type=int, default=1, dest="slippage_ticks")
    ap.add_argument("--tz", default="America/New_York")
    ap.add_argument("--source-tz", default=None, dest="source_tz")
    ap.add_argument("--timestamp", default="open", choices=["open", "close"])
    ap.add_argument("--out", default="mnq7_all")
    args = ap.parse_args()

    df = load_csv(args.csv, tz=args.tz, source_tz=args.source_tz, timestamp=args.timestamp)
    days = prepare_days(df)
    segs = segment_days(days, args.segments)
    base = Params(instrument=args.instrument, contracts=args.contracts,
                  commission_rt=args.commission_rt, slippage_ticks=args.slippage_ticks)

    full = pd.read_csv(args.grid)
    surv = full[(full["trades"] >= args.min_trades) & (full["net"] > 0)].copy()
    print(f"Loaded grid {args.grid}: {len(full)} combos. "
          f"Survivors (net>0, trades>={args.min_trades}): {len(surv)}", flush=True)
    for i, s in enumerate(segs, 1):
        print(f"  Segment {i}: {s[0]['date']} -> {s[-1]['date']}  ({len(s)} days)", flush=True)

    seg_cols = [f"seg{i+1}" for i in range(args.segments)]
    seg_net = {c: [] for c in seg_cols}
    min_seg, n_pos, min_seg_tr = [], [], []
    total = len(surv)
    for j, (_, r) in enumerate(surv.iterrows(), 1):
        p = _build_params(base, {k: r[k] for k in KEYS})
        nets, trs = [], []
        for s in segs:
            _, sm = run_prepared(s, p)
            nets.append(sm["net"])
            trs.append(sm["trades"])
        for i, c in enumerate(seg_cols):
            seg_net[c].append(nets[i])
        min_seg.append(min(nets))
        n_pos.append(sum(n > 0 for n in nets))
        min_seg_tr.append(min(trs))
        if j % 250 == 0 or j == total:
            print(f"  pass2 {j}/{total} survivors evaluated...", flush=True)

    for c in seg_cols:
        surv[c] = seg_net[c]
    surv["min_seg"] = min_seg
    surv["n_pos"] = n_pos
    surv["min_seg_trades"] = min_seg_tr

    robust = surv[(surv["n_pos"] == args.segments) &
                  (surv["min_seg_trades"] >= args.min_trades_seg)].copy()
    robust = robust.sort_values("min_seg", ascending=False)
    robust.to_csv(f"{args.out}_robust.csv", index=False)

    show = KEYS + ["trades", "win", "net", "pf", "maxdd"] + seg_cols + ["min_seg"]
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", None)
    print("\n" + "=" * 100)
    print(f"ROBUST WINNERS -- profitable in ALL {args.segments} segments, ranked by worst segment:")
    print(f"({len(robust)} configs qualified)\n", flush=True)
    print(robust[show].head(25).to_string(index=False), flush=True)
    print(f"\nSaved robust table -> {args.out}_robust.csv", flush=True)


if __name__ == "__main__":
    main()
