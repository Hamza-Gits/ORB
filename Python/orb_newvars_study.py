"""
orb_newvars_study.py
===================
Head-to-head test of the newest variables (fib entry, relative-volume filter,
volume-delta bias, overnight-gap filter, ATR target) against a fixed base config,
over the full history and every segment.

    python orb_newvars_study.py --csv MNQ_full_1min.csv --instrument MNQ \
        --rr 1.0 --or-minutes 30 --offset-ticks 1 --max-or-points 130
"""

import argparse
from dataclasses import replace

from orb_strategy import INSTRUMENTS, Params, load_csv, prepare_days, run_prepared
from orb_robustness import segment_days

VARIANTS = [
    ("baseline (touch entry)",      {}),
    ("FIB entry 0.5 (SL=swing low)", dict(entry_mode="fib", fib_entry=0.5)),
    ("FIB entry 0.618",             dict(entry_mode="fib", fib_entry=0.618)),
    ("RVOL >= 1.0 (avg+)",          dict(rvol_min=1.0)),
    ("RVOL >= 1.3 (busy days)",     dict(rvol_min=1.3)),
    ("bias = vdelta",               dict(bias="vdelta")),
    ("gap: skip large > 0.75%",     dict(gap_mode="skip_large", gap_pct=0.75)),
    ("gap: trade WITH gap",         dict(gap_mode="with")),
    ("gap: FADE gap",               dict(gap_mode="fade")),
    ("target = 1.0x ATR",           dict(target_mode="atr", target_atr_mult=1.0)),
    ("target = 1.5x ATR",           dict(target_mode="atr", target_atr_mult=1.5)),
]


def main():
    ap = argparse.ArgumentParser(description="Head-to-head test of the new variables")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--instrument", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--rr", type=float, default=1.0)
    ap.add_argument("--or-minutes", type=int, default=30, dest="or_minutes")
    ap.add_argument("--offset-ticks", type=int, default=1, dest="offset_ticks")
    ap.add_argument("--direction", default="both", choices=["both", "long", "short"])
    ap.add_argument("--max-or-points", type=float, default=130.0, dest="max_or_points")
    ap.add_argument("--segments", type=int, default=5)
    ap.add_argument("--commission-rt", type=float, default=1.24, dest="commission_rt")
    ap.add_argument("--slippage-ticks", type=int, default=1, dest="slippage_ticks")
    ap.add_argument("--tz", default="America/New_York")
    ap.add_argument("--source-tz", default=None, dest="source_tz")
    ap.add_argument("--timestamp", default="open", choices=["open", "close"])
    args = ap.parse_args()

    df = load_csv(args.csv, tz=args.tz, source_tz=args.source_tz, timestamp=args.timestamp)
    days = prepare_days(df)
    segs = segment_days(days, args.segments)
    base = Params(instrument=args.instrument, rr=args.rr, or_minutes=args.or_minutes,
                  offset_ticks=args.offset_ticks, direction=args.direction,
                  max_or_points=args.max_or_points,
                  commission_rt=args.commission_rt, slippage_ticks=args.slippage_ticks)

    print(f"\nBase: {args.instrument}  RR {args.rr}  OR {args.or_minutes}m  offset {args.offset_ticks}t  "
          f"dir {args.direction}  width<= {args.max_or_points:.0f}pt   ({args.segments} segments)")
    print(f"{'variant':28s} {'trades':>7s} {'win%':>6s} {'net$':>10s} {'PF':>5s} "
          f"{'maxDD$':>9s} {'worstSeg$':>10s}")
    print("-" * 82)
    for label, ov in VARIANTS:
        p = replace(base, **ov)
        _, m = run_prepared(days, p)
        seg_nets = [run_prepared(s, p)[1]["net"] for s in segs]
        pf = m["profit_factor"]
        pf_s = f"{pf:.2f}" if pf == pf and pf != float("inf") else "n/a"
        print(f"{label:28s} {m['trades']:>7.0f} {m['win_rate']:>6.1f} {m['net']:>10,.0f} "
              f"{pf_s:>5s} {m['max_drawdown']:>9,.0f} {min(seg_nets):>10,.0f}")

    print("\nKeep a variable only if it lifts PF and the WORST segment without gutting net.")


if __name__ == "__main__":
    main()
