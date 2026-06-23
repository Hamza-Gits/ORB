"""
orb_bias_study.py
================
Compare directional-bias / trend filters for a fixed ORB config. For each bias
mode it reports trades, win rate, net, profit factor, max drawdown, and the
WORST segment net (cross-time robustness) -- side by side with "no bias".

    python orb_bias_study.py --csv MNQ_1min.csv --instrument MNQ --rr 2 --or-minutes 30

Bias modes tested:
    none        baseline (both directions, whichever breaks first)
    ema_slope   daily EMA rising -> longs only, falling -> shorts only
    ema_price   OR-close price above daily EMA -> longs, below -> shorts
    vwap        OR-close price above intraday VWAP -> longs, below -> shorts
    vwap_slope  intraday VWAP rising across the OR -> longs, falling -> shorts

Use it with --max-or-points to stack the bias on top of the width filter.
"""

import argparse
from dataclasses import replace

from orb_strategy import INSTRUMENTS, Params, load_csv, prepare_days, run_prepared
from orb_robustness import segment_days

MODES = ["none", "ema_slope", "ema_price", "vwap", "vwap_slope"]


def main():
    ap = argparse.ArgumentParser(description="Compare bias/trend filters for one ORB config")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--instrument", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--or-minutes", type=int, default=30, dest="or_minutes")
    ap.add_argument("--offset-ticks", type=int, default=0, dest="offset_ticks")
    ap.add_argument("--max-or-points", type=float, default=0.0, dest="max_or_points",
                    help="optional OR-width filter to stack with the bias")
    ap.add_argument("--ema-period", type=int, default=20, dest="ema_period")
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
    segs = segment_days(days, args.segments)

    # Bias forces direction="both" so the filter, not a hard setting, picks the side.
    base = Params(instrument=args.instrument, rr=args.rr, or_minutes=args.or_minutes,
                  direction="both", offset_ticks=args.offset_ticks,
                  max_or_points=args.max_or_points, ema_period=args.ema_period,
                  contracts=args.contracts, commission_rt=args.commission_rt,
                  slippage_ticks=args.slippage_ticks)

    wf = f"  (width filter: OR <= {args.max_or_points:.0f}pt)" if args.max_or_points else ""
    print(f"\n{args.instrument}  RR {args.rr}  OR {args.or_minutes}m  offset {args.offset_ticks}t  "
          f"{args.contracts} contract(s){wf}")
    print(f"{'bias':12s} {'trades':>7s} {'win%':>6s} {'net$':>10s} {'PF':>5s} "
          f"{'maxDD$':>9s} {'worstSeg$':>10s}")
    print("-" * 64)
    for mode in MODES:
        p = replace(base, bias=mode)
        _, m = run_prepared(days, p)
        seg_nets = [run_prepared(s, p)[1]["net"] for s in segs]
        pf = m["profit_factor"]
        pf_s = f"{pf:.2f}" if pf == pf and pf != float("inf") else "n/a"
        print(f"{mode:12s} {m['trades']:>7.0f} {m['win_rate']:>6.1f} {m['net']:>10,.0f} "
              f"{pf_s:>5s} {m['max_drawdown']:>9,.0f} {min(seg_nets):>10,.0f}")

    print("\nA bias helps only if it lifts win%/PF and the WORST segment vs 'none'.")
    print("Fewer trades with a higher PF can still be the better account-friendly choice.")


if __name__ == "__main__":
    main()
