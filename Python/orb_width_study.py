"""
orb_width_study.py
==================
Test the idea: "skip days whose opening range is too WIDE (choppy / false-breakout
prone)." For a fixed strategy config, sweep the max-OR-width filter across the
percentiles of the actual OR-width distribution and see what it does to net P&L,
win rate, drawdown, and -- most importantly -- cross-segment robustness.

    python orb_width_study.py --csv MNQ_1min.csv --instrument MNQ --rr 2 --or-minutes 30

Reads the OR-width distribution first so the thresholds are meaningful for the
instrument and OR length you chose (a 30-min MNQ range is far wider than a 5-min one).
"""

import argparse
from dataclasses import replace

import numpy as np

from orb_strategy import INSTRUMENTS, Params, load_csv, prepare_days, run_prepared, _time_to_sec
from orb_robustness import segment_days


def or_widths(days, or_start, or_minutes):
    o0 = _time_to_sec(or_start)
    o1 = o0 + or_minutes * 60
    w = []
    for d in days:
        sec = d["sec"]
        m = (sec >= o0) & (sec < o1)
        if not m.any():
            continue
        hi = float(d["high"][m].max())
        lo = float(d["low"][m].min())
        if hi > lo:
            w.append(hi - lo)
    return np.array(w)


def main():
    ap = argparse.ArgumentParser(description="Sweep the OR-width volatility filter")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--instrument", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--or-minutes", type=int, default=30, dest="or_minutes")
    ap.add_argument("--direction", default="both", choices=["both", "long", "short"])
    ap.add_argument("--offset-ticks", type=int, default=0, dest="offset_ticks")
    ap.add_argument("--contracts", type=int, default=1)
    ap.add_argument("--segments", type=int, default=4)
    ap.add_argument("--commission-rt", type=float, default=1.24, dest="commission_rt")
    ap.add_argument("--slippage-ticks", type=int, default=1, dest="slippage_ticks")
    ap.add_argument("--tz", default="America/New_York")
    ap.add_argument("--source-tz", default=None, dest="source_tz")
    ap.add_argument("--timestamp", default="open", choices=["open", "close"])
    args = ap.parse_args()

    df = load_csv(args.csv, tz=args.tz, source_tz=args.source_tz, timestamp=args.timestamp)
    days = prepare_days(df)
    base = Params(instrument=args.instrument, rr=args.rr, or_minutes=args.or_minutes,
                  direction=args.direction, offset_ticks=args.offset_ticks,
                  contracts=args.contracts, commission_rt=args.commission_rt,
                  slippage_ticks=args.slippage_ticks)

    w = or_widths(days, base.or_start, args.or_minutes)
    print(f"\n{args.instrument}  {args.or_minutes}-min OR width (points) over {len(w)} days:")
    qs = [10, 25, 50, 60, 70, 75, 80, 90, 95]
    pcts = {q: np.percentile(w, q) for q in qs}
    print("  mean {:.1f}   median {:.1f}".format(w.mean(), np.median(w)))
    print("  percentiles: " + "  ".join(f"p{q}={pcts[q]:.0f}" for q in qs))

    segs = segment_days(days, args.segments)

    thresholds = [("none (no filter)", 0.0)]
    for q in [90, 80, 75, 70, 60, 50]:
        thresholds.append((f"OR < p{q} (<={pcts[q]:.0f}pt)", float(pcts[q])))

    print(f"\nConfig: RR {args.rr}  OR {args.or_minutes}m  dir {args.direction}  "
          f"offset {args.offset_ticks}t  {args.contracts} contract(s)")
    print(f"{'filter':22s} {'maxOR':>6s} {'trades':>7s} {'win%':>6s} {'net$':>10s} "
          f"{'PF':>5s} {'maxDD$':>9s} {'worstSeg$':>10s}")
    print("-" * 84)
    for label, mx in thresholds:
        p = replace(base, max_or_points=mx)
        _, m = run_prepared(days, p)
        seg_nets = [run_prepared(s, p)[1]["net"] for s in segs]
        pf = m["profit_factor"]
        pf_s = f"{pf:.2f}" if pf == pf and pf != float("inf") else "n/a"
        print(f"{label:22s} {mx:>6.0f} {m['trades']:>7.0f} {m['win_rate']:>6.1f} "
              f"{m['net']:>10,.0f} {pf_s:>5s} {m['max_drawdown']:>9,.0f} {min(seg_nets):>10,.0f}")

    print("\nRead it like this: if a tighter max-OR filter raises net AND raises the worst")
    print("segment (worstSeg$) AND cuts maxDD, skipping wide days is a real improvement.")
    print("If net just falls as you filter more, the wide days were not the problem.")


if __name__ == "__main__":
    main()
