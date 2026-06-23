"""
orb_exit_study.py
================
Compare Tier-2 exit-management variables against a fixed base config:
breakeven, trailing stop, partial scale-out, and volume confirmation. Each
variant runs over the full history AND every segment.

    python orb_exit_study.py --csv MNQ_1min.csv --instrument MNQ \
        --rr 1.0 --or-minutes 30 --offset-ticks 1 --max-or-points 130

Scale-out variants need >= 2 contracts, so they are run with --contracts 2 here
(the others use 1). Watch net, profit factor, max drawdown, and worst segment.
"""

import argparse
from dataclasses import replace

from orb_strategy import INSTRUMENTS, Params, load_csv, prepare_days, run_prepared
from orb_robustness import segment_days

# (label, param-overrides, contracts)
VARIANTS = [
    ("baseline",                       {}, 1),
    ("breakeven @1R",                  dict(breakeven_r=1.0), 1),
    ("breakeven @0.5R",                dict(breakeven_r=0.5), 1),
    ("trail 20 ticks",                 dict(trail_mode="ticks", trail_ticks=20), 1),
    ("trail 40 ticks",                 dict(trail_mode="ticks", trail_ticks=40), 1),
    ("trail 1.0x ATR",                 dict(trail_mode="atr", trail_atr_mult=1.0), 1),
    ("trail 2.0x ATR",                 dict(trail_mode="atr", trail_atr_mult=2.0), 1),
    ("vol confirm 1.2x",               dict(vol_confirm_mult=1.2), 1),
    ("vol confirm 1.5x",               dict(vol_confirm_mult=1.5), 1),
    ("2 lots, no scale",               {}, 2),
    ("2 lots, scale half @1R",         dict(scale_out_r=1.0, scale_frac=0.5), 2),
    ("2 lots, scale half @1.5R",       dict(scale_out_r=1.5, scale_frac=0.5), 2),
    ("2 lots, scale @1R + BE",         dict(scale_out_r=1.0, scale_frac=0.5, breakeven_r=1.0), 2),
]


def main():
    ap = argparse.ArgumentParser(description="Compare Tier-2 exit-management variables")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--instrument", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--rr", type=float, default=1.0)
    ap.add_argument("--or-minutes", type=int, default=30, dest="or_minutes")
    ap.add_argument("--offset-ticks", type=int, default=1, dest="offset_ticks")
    ap.add_argument("--direction", default="both", choices=["both", "long", "short"])
    ap.add_argument("--max-or-points", type=float, default=130.0, dest="max_or_points")
    ap.add_argument("--bias", default="none",
                    choices=["none", "ema_slope", "ema_price", "vwap", "vwap_slope"])
    ap.add_argument("--segments", type=int, default=4)
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
                  max_or_points=args.max_or_points, bias=args.bias,
                  commission_rt=args.commission_rt, slippage_ticks=args.slippage_ticks)

    print(f"\nBase: {args.instrument}  RR {args.rr}  OR {args.or_minutes}m  offset {args.offset_ticks}t  "
          f"dir {args.direction}  width<= {args.max_or_points:.0f}pt  bias {args.bias}")
    print(f"{'variant':28s} {'lots':>4s} {'trades':>7s} {'win%':>6s} {'net$':>10s} "
          f"{'PF':>5s} {'maxDD$':>9s} {'worstSeg$':>10s}")
    print("-" * 86)
    for label, ov, lots in VARIANTS:
        p = replace(base, contracts=lots, **ov)
        _, m = run_prepared(days, p)
        seg_nets = [run_prepared(s, p)[1]["net"] for s in segs]
        pf = m["profit_factor"]
        pf_s = f"{pf:.2f}" if pf == pf and pf != float("inf") else "n/a"
        print(f"{label:28s} {lots:>4d} {m['trades']:>7.0f} {m['win_rate']:>6.1f} "
              f"{m['net']:>10,.0f} {pf_s:>5s} {m['max_drawdown']:>9,.0f} {min(seg_nets):>10,.0f}")

    print("\nNote: '2 lots' rows are double size, so compare their net/maxDD to '2 lots, no")
    print("scale', not to the 1-lot baseline. A good exit lifts net or worstSeg without")
    print("worsening maxDD proportionally.")


if __name__ == "__main__":
    main()
