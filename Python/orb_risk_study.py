"""
orb_risk_study.py
================
Compare Tier-1 risk / durability variables against a fixed base config:
stop design, constant-$ position sizing, regime (trend) filter, event-day skip,
and entry-cutoff time. Each variant is run over the full history AND every
segment, so you see net, profit factor, max drawdown, average contracts, and the
WORST segment (robustness) side by side.

    python orb_risk_study.py --csv MNQ_1min.csv --instrument MNQ \
        --rr 1.0 --or-minutes 30 --offset-ticks 1 --max-or-points 130

Default base = the prop-safe winner from orb_final.py.
"""

import argparse
from dataclasses import replace

from orb_strategy import INSTRUMENTS, Params, load_csv, prepare_days, run_prepared
from orb_robustness import segment_days

VARIANTS = [
    ("baseline (OR stop, 1 lot)",   {}),
    ("stop: 25pt fixed",            dict(stop_mode="points", stop_points=25)),
    ("stop: 40pt fixed",            dict(stop_mode="points", stop_points=40)),
    ("stop: 0.50x OR",              dict(stop_mode="or_frac", stop_or_frac=0.5)),
    ("stop: 0.75x OR",              dict(stop_mode="or_frac", stop_or_frac=0.75)),
    ("stop: 1.0x ATR",              dict(stop_mode="atr", stop_atr_mult=1.0)),
    ("stop: 1.5x ATR",              dict(stop_mode="atr", stop_atr_mult=1.5)),
    ("regime ADX>=20",              dict(regime="adx", regime_adx_min=20)),
    ("regime ADX>=25",              dict(regime="adx", regime_adx_min=25)),
    ("regime MA50 trend",           dict(regime="ma", regime_ma_period=50)),
    ("skip NFP + OpEx",             dict(skip_nfp=True, skip_opex=True)),
    ("entry cutoff 11:30",          dict(entry_cutoff="11:30")),
    ("entry cutoff 12:00",          dict(entry_cutoff="12:00")),
    ("const-$ risk $300 (OR stop)", dict(risk_dollars=300)),
    ("const-$ $300 + 25pt stop",    dict(risk_dollars=300, stop_mode="points", stop_points=25)),
]


def main():
    ap = argparse.ArgumentParser(description="Compare Tier-1 risk/durability variables")
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
    print(f"{'variant':30s} {'trades':>7s} {'win%':>6s} {'avgCt':>6s} {'net$':>10s} "
          f"{'PF':>5s} {'maxDD$':>9s} {'worstSeg$':>10s}")
    print("-" * 92)
    for label, ov in VARIANTS:
        p = replace(base, **ov)
        tr, m = run_prepared(days, p)
        seg_nets = [run_prepared(s, p)[1]["net"] for s in segs]
        avg_ct = tr["contracts"].mean() if len(tr) else 0.0
        pf = m["profit_factor"]
        pf_s = f"{pf:.2f}" if pf == pf and pf != float("inf") else "n/a"
        print(f"{label:30s} {m['trades']:>7.0f} {m['win_rate']:>6.1f} {avg_ct:>6.1f} "
              f"{m['net']:>10,.0f} {pf_s:>5s} {m['max_drawdown']:>9,.0f} {min(seg_nets):>10,.0f}")

    print("\nFor prop accounts: watch maxDD and worstSeg, not just net. A variable that cuts")
    print("maxDD while keeping net/worstSeg positive is a real upgrade. const-$ sizing scales")
    print("net AND maxDD together (more contracts) -- judge it per your account's DD limit.")


if __name__ == "__main__":
    main()
