"""
dd_analysis.py
=============
Drawdown / risk report for one strategy config at a chosen contract size --
built to answer "can I run this on an X-dollar prop account?"

    python dd_analysis.py --csv MNQ_1min.csv --instrument MNQ --rr 2 --or-minutes 30 \
                          --direction both --contracts 2

Reports the closed-trade max drawdown, worst day, worst single trade, worst
losing streak, and the daily-loss distribution, then sizes it against a prop
account's trailing-drawdown and daily-loss limits.

NOTE: prop firms measure a TRAILING (intraday, unrealized-peak) drawdown. This
report uses CLOSED-trade equity, so the real trailing figure will be somewhat
WORSE than the maxDD shown here. Treat these numbers as a floor, not a ceiling.
"""

import argparse

import numpy as np

from orb_strategy import INSTRUMENTS, Params, load_csv, prepare_days, run_prepared


def losing_streak(nets):
    cur_len = cur_sum = 0
    max_len = 0
    max_depth = 0.0
    for v in nets:
        if v < 0:
            cur_len += 1
            cur_sum += v
            max_len = max(max_len, cur_len)
            max_depth = min(max_depth, cur_sum)
        else:
            cur_len = cur_sum = 0
    return max_len, max_depth


def main():
    ap = argparse.ArgumentParser(description="Drawdown / prop-account risk report")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--instrument", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--or-minutes", type=int, default=30, dest="or_minutes")
    ap.add_argument("--direction", default="both", choices=["both", "long", "short"])
    ap.add_argument("--offset-ticks", type=int, default=0, dest="offset_ticks")
    ap.add_argument("--contracts", type=int, default=1)
    ap.add_argument("--min-or-points", type=float, default=0.0, dest="min_or_points")
    ap.add_argument("--max-or-points", type=float, default=0.0, dest="max_or_points")
    ap.add_argument("--commission-rt", type=float, default=1.24, dest="commission_rt")
    ap.add_argument("--slippage-ticks", type=int, default=1, dest="slippage_ticks")
    ap.add_argument("--account", type=float, default=25000, help="account size for context ($)")
    ap.add_argument("--trailing-dd", type=float, default=1500,
                    help="prop trailing drawdown limit for context ($)")
    ap.add_argument("--daily-loss", type=float, default=500,
                    help="prop daily-loss limit for context ($)")
    ap.add_argument("--tz", default="America/New_York")
    ap.add_argument("--source-tz", default=None, dest="source_tz")
    ap.add_argument("--timestamp", default="open", choices=["open", "close"])
    args = ap.parse_args()

    df = load_csv(args.csv, tz=args.tz, source_tz=args.source_tz, timestamp=args.timestamp)
    days = prepare_days(df)
    p = Params(instrument=args.instrument, rr=args.rr, or_minutes=args.or_minutes,
               direction=args.direction, offset_ticks=args.offset_ticks, contracts=args.contracts,
               commission_rt=args.commission_rt, slippage_ticks=args.slippage_ticks,
               min_or_points=args.min_or_points, max_or_points=args.max_or_points)
    trades, m = run_prepared(days, p)
    if len(trades) == 0:
        print("No trades for this config.")
        return

    nets = trades["net"].to_numpy()
    eq = np.cumsum(nets)
    dd = eq - np.maximum.accumulate(eq)
    max_dd = dd.min()
    daily = trades.groupby("date")["net"].sum()
    sl_len, sl_depth = losing_streak(nets)

    print("\n========== RISK REPORT ==========")
    print(f"  Config        : {args.instrument}  RR {args.rr}  OR {args.or_minutes}m  "
          f"dir {args.direction}  offset {args.offset_ticks}t")
    if args.max_or_points or args.min_or_points:
        print(f"  OR-width filter: keep {args.min_or_points or 0:.0f} - "
              f"{args.max_or_points or 'inf'} points")
    print(f"  Contracts     : {args.contracts}")
    print(f"  Period        : {trades['date'].min()}  ->  {trades['date'].max()}")
    print(f"  Trades        : {len(trades)}   Win rate: {m['win_rate']:.1f}%")
    print(f"  Net P&L       : ${m['net']:,.0f}")
    print("  --- risk ---")
    print(f"  Max drawdown (closed-trade)   : ${max_dd:,.0f}")
    print(f"  Worst single trade            : ${nets.min():,.0f}")
    print(f"  Worst single DAY              : ${daily.min():,.0f}")
    print(f"  Worst losing streak           : {sl_len} trades, ${sl_depth:,.0f} deep")
    print(f"  Avg loss / 95th-pct day loss  : ${nets[nets < 0].mean():,.0f}  /  "
          f"${np.percentile(daily, 5):,.0f}")

    print("\n========== vs PROP ACCOUNT ==========")
    print(f"  Account size            : ${args.account:,.0f}")
    print(f"  Trailing DD limit (~)   : ${args.trailing_dd:,.0f}")
    print(f"  Daily-loss limit (~)    : ${args.daily_loss:,.0f}")
    dd_ratio = abs(max_dd) / args.trailing_dd
    print(f"  Strategy maxDD is {dd_ratio:.1f}x the trailing-DD limit "
          f"({'BREACHES' if dd_ratio >= 1 else 'within'} it on closed equity alone)")
    breach_days = int((daily < -args.daily_loss).sum())
    print(f"  Days exceeding the daily-loss limit: {breach_days} of {len(daily)} "
          f"({100*breach_days/len(daily):.1f}%)")
    print("\n  Reminder: prop trailing DD is measured intrabar off the equity HIGH, so the")
    print("  real breach risk is worse than these closed-trade figures.")


if __name__ == "__main__":
    main()
