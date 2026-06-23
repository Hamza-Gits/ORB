"""
orb_final.py
===========
The full, final ORB optimization. Sweeps every dimension we built -- reward:risk,
OR length, breakout offset, direction, OR-width volatility filter, and VWAP bias --
then ranks the survivors by CROSS-SEGMENT ROBUSTNESS, not by raw in-sample profit.

Two passes (for speed):
  1. Run the whole grid over the full history; keep configs that are net-positive
     with enough trades.
  2. Re-run only those survivors on each time segment; keep the ones that make
     money in EVERY segment and rank them by their WORST segment.

The winner is the config that held up across all periods -- the closest thing to
a real, non-curve-fit edge this data can give you.

    python orb_final.py --csv MNQ_1min.csv --instrument MNQ --segments 4 --out mnq_final

Note: EMA bias is intentionally excluded -- it underperformed VWAP bias and its
daily-EMA warmup distorts per-segment testing. VWAP bias is computed intraday and
is clean to segment.
"""

import argparse
import itertools
from dataclasses import replace

import pandas as pd

from orb_strategy import INSTRUMENTS, Params, load_csv, prepare_days, run_prepared
from orb_robustness import segment_days

# The full search space. or_minutes is trimmed to the lengths that proved useful
# on both instruments (15/30/60); the short ORs were consistently weak.
GRID = {
    "or_minutes":    [5, 10, 15, 30, 60],
    "offset_ticks":  [0, 1, 2],
    "direction":     ["both", "long", "short"],
    "bias":          ["none", "vwap_slope"],   # vwap_slope = the proven bias
    "max_or_points": [0, 130, 200],
    "regime":        ["none", "adx"],          # adx uses regime_adx_min (default 20)
    # 'target' combines reward:risk and ATR-target styles in one dimension
    "target":        ["rr1.0", "rr1.5", "rr2.0", "rr2.5", "rr3.0",
                      "atr1.0", "atr1.5", "atr2.0", "atr2.5"],
}
KEYS = list(GRID.keys())


def _typed(k, v):
    """Coerce a results-row cell back to the correct Params type."""
    if k in ("or_minutes", "offset_ticks"):
        return int(v)
    if k == "max_or_points":
        return float(v)
    return str(v)


def _build_params(base, kw):
    """Build a Params from a grid row, translating the composite 'target' token."""
    kw = dict(kw)
    tgt = kw.pop("target", None)
    p = replace(base, **{k: _typed(k, val) for k, val in kw.items()})
    if tgt is not None:
        tgt = str(tgt)
        if tgt.startswith("atr"):
            p = replace(p, target_mode="atr", target_atr_mult=float(tgt[3:]))
        else:
            p = replace(p, target_mode="rr", rr=float(tgt[2:]))
    return p


def main():
    ap = argparse.ArgumentParser(description="Full final ORB optimization, robustness-ranked")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--instrument", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--segments", type=int, default=4)
    ap.add_argument("--min-trades", type=int, default=150, dest="min_trades",
                    help="min full-period trades to survive pass 1")
    ap.add_argument("--min-trades-seg", type=int, default=25, dest="min_trades_seg",
                    help="min trades in EVERY segment to qualify as robust")
    ap.add_argument("--contracts", type=int, default=1)
    ap.add_argument("--commission-rt", type=float, default=1.24, dest="commission_rt")
    ap.add_argument("--slippage-ticks", type=int, default=1, dest="slippage_ticks")
    ap.add_argument("--tz", default="America/New_York")
    ap.add_argument("--source-tz", default=None, dest="source_tz")
    ap.add_argument("--timestamp", default="open", choices=["open", "close"])
    ap.add_argument("--out", default="mnq_final")
    args = ap.parse_args()

    df = load_csv(args.csv, tz=args.tz, source_tz=args.source_tz, timestamp=args.timestamp)
    days = prepare_days(df)
    segs = segment_days(days, args.segments)
    base = Params(instrument=args.instrument, contracts=args.contracts,
                  commission_rt=args.commission_rt, slippage_ticks=args.slippage_ticks)

    combos = list(itertools.product(*[GRID[k] for k in KEYS]))
    print(f"Loaded {len(df):,} bars. Full grid = {len(combos):,} combinations.")
    for i, s in enumerate(segs, 1):
        print(f"  Segment {i}: {s[0]['date']} -> {s[-1]['date']}  ({len(s)} days)")

    # ---- pass 1: full period ----
    rows = []
    for combo in combos:
        kw = dict(zip(KEYS, combo))
        _, m = run_prepared(days, _build_params(base, kw))
        rows.append({**kw, "trades": m["trades"], "net": m["net"],
                     "pf": m["profit_factor"], "win": m["win_rate"],
                     "maxdd": m["max_drawdown"]})
    full = pd.DataFrame(rows)
    full.to_csv(f"{args.out}_fullgrid.csv", index=False)
    print(f"Pass 1 done. Saved full grid -> {args.out}_fullgrid.csv")

    surv = full[(full["trades"] >= args.min_trades) & (full["net"] > 0)].copy()
    print(f"Pass 1 survivors (net>0, trades>={args.min_trades}): {len(surv)} / {len(full)}")

    # ---- pass 2: segment robustness on survivors ----
    seg_cols = [f"seg{i+1}" for i in range(args.segments)]
    seg_net = {c: [] for c in seg_cols}
    min_seg, n_pos, min_seg_tr = [], [], []
    for _, r in surv.iterrows():
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
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", None)

    print("\n" + "=" * 100)
    print(f"OVERFIT PICK (highest in-sample net -- do NOT trust this one):")
    top_net = full[full["trades"] >= args.min_trades].sort_values("net", ascending=False).iloc[0]
    print("  " + "  ".join(f"{k}={top_net[k]}" for k in KEYS) +
          f"   net=${top_net['net']:,.0f}  pf={top_net['pf']:.2f}  maxDD=${top_net['maxdd']:,.0f}")

    print("\n" + "=" * 100)
    print(f"ROBUST WINNERS -- profitable in ALL {args.segments} segments, ranked by worst segment:")
    print(f"({len(robust)} configs qualified)\n")
    print(robust[show].head(20).to_string(index=False))

    # prop-friendly subset: drawdown that fits a ~$1,500 trailing limit on 1 contract
    prop = robust[robust["maxdd"] >= -1500].sort_values("min_seg", ascending=False)
    print("\n" + "=" * 100)
    print("PROP-FRIENDLY ROBUST CONFIGS (max drawdown within ~$1,500, 1 contract):")
    if len(prop):
        print(prop[show].head(10).to_string(index=False))
        b = prop.iloc[0]
        print("\nRECOMMENDED (robust + account-safe):")
        print("  " + "  ".join(f"{k}={b[k]}" for k in KEYS))
        print(f"  -> net ${b['net']:,.0f}  PF {b['pf']:.2f}  win {b['win']:.1f}%  "
              f"maxDD ${b['maxdd']:,.0f}  worst-segment ${b['min_seg']:,.0f}")
        cmd = f"python orb_backtest.py --csv {args.csv} --instrument {args.instrument}"
        for k in KEYS:
            if k == "target":
                t = str(b[k])
                cmd += (f" --target-mode atr --target-atr-mult {t[3:]}" if t.startswith("atr")
                        else f" --rr {t[2:]}")
            else:
                cmd += f" --{k.replace('_', '-')} {_typed(k, b[k])}"
        print(f"  reproduce: {cmd}")
    else:
        print("  (none within $1,500 -- the robust edge needs more than 1 contract of room)")

    print(f"\nSaved robust table -> {args.out}_robust.csv")


if __name__ == "__main__":
    main()
