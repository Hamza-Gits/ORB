"""
orb_entry_study.py
=================
Compare ENTRY styles for a fixed ORB config -- does waiting for confirmation
beat entering on the first touch of the level?

    stop     enter on first touch of ORH/ORL (the default; catches everything,
             including wick-only false breakouts)
    close    enter only when a 1-min bar CLOSES beyond the level
    rebreak  break -> a bar closes back inside -> break again, then enter
    retest   break (close beyond) -> pullback to the level -> enter there

For each style it reports trades, win%, net, profit factor, max drawdown, average
R, and the WORST segment net (cross-time robustness).

    python orb_entry_study.py --csv MNQ_1min.csv --instrument MNQ --rr 2 --or-minutes 30
    python orb_entry_study.py --csv MNQ_1min.csv --instrument MNQ --rr 2 --or-minutes 30 \
                              --max-or-points 130 --bias vwap_slope
"""

import argparse
from dataclasses import replace

from orb_strategy import INSTRUMENTS, Params, load_csv, prepare_days, run_prepared
from orb_robustness import segment_days

MODES = ["stop", "close", "rebreak", "retest"]


def main():
    ap = argparse.ArgumentParser(description="Compare ORB entry styles for one config")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--instrument", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--or-minutes", type=int, default=30, dest="or_minutes")
    ap.add_argument("--direction", default="both", choices=["both", "long", "short"])
    ap.add_argument("--offset-ticks", type=int, default=0, dest="offset_ticks")
    ap.add_argument("--max-or-points", type=float, default=0.0, dest="max_or_points")
    ap.add_argument("--bias", default="none",
                    choices=["none", "ema_slope", "ema_price", "vwap", "vwap_slope"])
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
    base = Params(instrument=args.instrument, rr=args.rr, or_minutes=args.or_minutes,
                  direction=args.direction, offset_ticks=args.offset_ticks,
                  max_or_points=args.max_or_points, bias=args.bias, contracts=args.contracts,
                  commission_rt=args.commission_rt, slippage_ticks=args.slippage_ticks)

    extra = []
    if args.max_or_points:
        extra.append(f"width<= {args.max_or_points:.0f}pt")
    if args.bias != "none":
        extra.append(f"bias {args.bias}")
    tag = ("  [" + ", ".join(extra) + "]") if extra else ""
    print(f"\n{args.instrument}  RR {args.rr}  OR {args.or_minutes}m  dir {args.direction}  "
          f"offset {args.offset_ticks}t{tag}")
    print(f"{'entry':9s} {'trades':>7s} {'win%':>6s} {'net$':>10s} {'PF':>5s} "
          f"{'avgR':>6s} {'maxDD$':>9s} {'worstSeg$':>10s}")
    print("-" * 70)
    for mode in MODES:
        p = replace(base, entry_mode=mode)
        _, m = run_prepared(days, p)
        seg_nets = [run_prepared(s, p)[1]["net"] for s in segs]
        pf = m["profit_factor"]
        pf_s = f"{pf:.2f}" if pf == pf and pf != float("inf") else "n/a"
        print(f"{mode:9s} {m['trades']:>7.0f} {m['win_rate']:>6.1f} {m['net']:>10,.0f} "
              f"{pf_s:>5s} {m['avg_R']:>6.2f} {m['max_drawdown']:>9,.0f} {min(seg_nets):>10,.0f}")

    print("\nConfirmation entries (close/rebreak/retest) should lift win% and cut false")
    print("breakouts, but they enter worse and skip clean runaways -- watch net & worstSeg.")


if __name__ == "__main__":
    main()
