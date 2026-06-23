"""
orb_pass2_par.py
================
Parallel Pass 2 (segment robustness) reading a saved Pass-1 full grid CSV.
Same logic as orb_pass2.py but fans the survivors across all CPU cores with a
ProcessPoolExecutor -- each worker loads the data once (Windows spawn-safe via an
initializer) and only tiny per-config results cross the pipe.

    python orb_pass2_par.py --csv MNQ_full_1min.csv --grid mnq7_all_fullgrid.csv \
        --segments 5 --out mnq7_all --workers 7
"""

import argparse
import os
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from orb_strategy import INSTRUMENTS, Params, load_csv, prepare_days, run_prepared
from orb_robustness import segment_days
from orb_final import KEYS, _build_params

_SEGS = None
_BASE = None


def _init(csv, instrument, segments, tz, source_tz, timestamp, commission, slippage):
    global _SEGS, _BASE
    df = load_csv(csv, tz=tz, source_tz=source_tz, timestamp=timestamp)
    days = prepare_days(df)
    _SEGS = segment_days(days, segments)
    _BASE = Params(instrument=instrument, commission_rt=commission, slippage_ticks=slippage)


def _eval(row_kw):
    p = _build_params(_BASE, row_kw)
    nets, trs = [], []
    for s in _SEGS:
        _, sm = run_prepared(s, p)
        nets.append(sm["net"])
        trs.append(sm["trades"])
    return nets, trs


def main():
    ap = argparse.ArgumentParser(description="Parallel robustness Pass 2 from a saved grid")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--grid", required=True)
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
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--out", default="mnq7_all")
    args = ap.parse_args()

    # segment date labels (load once in the parent just for the printout)
    df = load_csv(args.csv, tz=args.tz, source_tz=args.source_tz, timestamp=args.timestamp)
    days = prepare_days(df)
    segs = segment_days(days, args.segments)
    del days, df

    full = pd.read_csv(args.grid)
    surv = full[(full["trades"] >= args.min_trades) & (full["net"] > 0)].copy().reset_index(drop=True)
    print(f"Loaded grid {args.grid}: {len(full)} combos. "
          f"Survivors (net>0, trades>={args.min_trades}): {len(surv)}", flush=True)
    for i, s in enumerate(segs, 1):
        print(f"  Segment {i}: {s[0]['date']} -> {s[-1]['date']}  ({len(s)} days)", flush=True)
    print(f"Fanning out across {args.workers} workers...", flush=True)

    rows_kw = [{k: surv.at[idx, k] for k in KEYS} for idx in range(len(surv))]

    seg_cols = [f"seg{i+1}" for i in range(args.segments)]
    results = [None] * len(rows_kw)
    total = len(rows_kw)
    done = 0
    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=_init,
        initargs=(args.csv, args.instrument, args.segments, args.tz,
                  args.source_tz, args.timestamp, args.commission_rt, args.slippage_ticks),
    ) as ex:
        for i, res in enumerate(ex.map(_eval, rows_kw, chunksize=8)):
            results[i] = res
            done += 1
            if done % 500 == 0 or done == total:
                print(f"  pass2 {done}/{total} survivors evaluated...", flush=True)

    seg_net = {c: [] for c in seg_cols}
    min_seg, n_pos, min_seg_tr = [], [], []
    for nets, trs in results:
        for i, c in enumerate(seg_cols):
            seg_net[c].append(nets[i])
        min_seg.append(min(nets))
        n_pos.append(sum(n > 0 for n in nets))
        min_seg_tr.append(min(trs))
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
