"""
orb_explore_oos.py
==================
Disciplined parameter exploration with a LOCKED out-of-sample vault.

We search new/under-explored dimensions ONLY on the in-sample window (2019-2023),
rank candidates by their worst in-sample sub-segment (robustness, not max net),
then evaluate the top survivors -- plus the current champion -- ONCE on the
out-of-sample window (2024-2026) that the search never touched.

A variant is a real improvement only if it beats the champion BOTH in-sample
(robustly) AND out-of-sample. Anything that only wins in-sample is curve-fit.

    python orb_explore_oos.py
"""

import itertools
from dataclasses import replace

import numpy as np
import pandas as pd

from orb_strategy import Params, load_csv, prepare_days, run_prepared
from orb_robustness import segment_days

OOS_START = pd.Timestamp("2024-01-01").date()   # everything >= this is the locked vault

# the current champion (fixed core); we vary only the dims below around it
CHAMP = dict(or_minutes=15, offset_ticks=2, direction="both", bias="vwap_slope",
             max_or_points=130.0, regime="adx", regime_adx_min=20.0,
             target_mode="atr", target_atr_mult=1.5, entry_cutoff="", min_or_points=0.0)

GRID = {
    "entry_cutoff":    ["", "11:00", "12:00", "13:00"],
    "min_or_points":   [0.0, 20.0, 30.0],
    "regime_adx_min":  [18.0, 20.0, 25.0],
    "target_atr_mult": [1.5, 2.0, 3.0],
}
KEYS = list(GRID.keys())


def stats(days, p):
    _, m = run_prepared(days, p)
    return m["net"], m["profit_factor"], m["win_rate"], m["max_drawdown"], m["trades"]


def main():
    df = load_csv("MNQ_full_1min.csv", tz="America/New_York")
    days = prepare_days(df)
    is_days = [d for d in days if d["date"] < OOS_START]
    oos_days = [d for d in days if d["date"] >= OOS_START]
    is_segs = segment_days(is_days, 3)
    base = Params(instrument="MNQ", commission_rt=1.24, slippage_ticks=1)

    print(f"In-sample : {is_days[0]['date']} -> {is_days[-1]['date']}  ({len(is_days)} days)")
    print(f"Out-of-sample (LOCKED): {oos_days[0]['date']} -> {oos_days[-1]['date']}  ({len(oos_days)} days)")
    print(f"Grid: {np.prod([len(GRID[k]) for k in KEYS])} combos\n")

    champ = replace(base, **CHAMP)
    c_is = stats(is_days, champ)
    c_oos = stats(oos_days, champ)
    print("CHAMPION (current):")
    print(f"  IN-SAMPLE  net ${c_is[0]:>8,.0f}  PF {c_is[1]:.2f}  win {c_is[2]:.1f}%  maxDD ${c_is[3]:>7,.0f}  ({c_is[4]} tr)")
    print(f"  OUT-SAMPLE net ${c_oos[0]:>8,.0f}  PF {c_oos[1]:.2f}  win {c_oos[2]:.1f}%  maxDD ${c_oos[3]:>7,.0f}  ({c_oos[4]} tr)\n")

    # ---- search on IN-SAMPLE only ----
    rows = []
    for combo in itertools.product(*[GRID[k] for k in KEYS]):
        kw = dict(zip(KEYS, combo))
        p = replace(base, **{**CHAMP, **kw})
        seg_nets = [run_prepared(s, p)[1]["net"] for s in is_segs]
        net, pf, win, dd, tr = stats(is_days, p)
        rows.append({**kw, "is_net": net, "is_pf": pf, "is_win": win, "is_dd": dd,
                     "is_tr": tr, "is_worstseg": min(seg_nets), "is_allpos": all(n > 0 for n in seg_nets)})
    res = pd.DataFrame(rows)

    # robust IS survivors: positive in every IS sub-segment, ranked by worst segment
    robust = res[res["is_allpos"]].sort_values("is_worstseg", ascending=False)
    print(f"In-sample robust survivors (positive in all 3 IS segments): {len(robust)}/{len(res)}")

    # ---- validate top IS candidates on the LOCKED OOS ----
    top = robust.head(8)
    print("\nTop in-sample candidates, then their OUT-OF-SAMPLE result (never optimized on):")
    print(f"{'cutoff':>7} {'minOR':>6} {'adx':>5} {'atr':>4} | {'IS net':>8} {'IS PF':>5} {'IS wseg':>8} | "
          f"{'OOS net':>8} {'OOS PF':>6} {'OOS win':>7} {'OOS DD':>7}")
    print("-" * 104)
    champ_oos_net = c_oos[0]
    beat = []
    for _, r in top.iterrows():
        kw = {k: r[k] for k in KEYS}
        p = replace(base, **{**CHAMP, **kw})
        o = stats(oos_days, p)
        flag = "  <-- beats champ OOS" if o[0] > champ_oos_net else ""
        if o[0] > champ_oos_net:
            beat.append((kw, o))
        cut = r["entry_cutoff"] or "none"
        print(f"{cut:>7} {r['min_or_points']:>6.0f} {r['regime_adx_min']:>5.0f} {r['target_atr_mult']:>4.1f} | "
              f"{r['is_net']:>8,.0f} {r['is_pf']:>5.2f} {r['is_worstseg']:>8,.0f} | "
              f"{o[0]:>8,.0f} {o[1]:>6.2f} {o[2]:>6.1f}% {o[3]:>7,.0f}{flag}")

    print("\n" + "=" * 104)
    print(f"CHAMPION out-of-sample net: ${champ_oos_net:,.0f}  (PF {c_oos[1]:.2f})")
    if beat:
        print(f"{len(beat)} candidate(s) beat the champion OUT-OF-SAMPLE -> genuine improvement worth a closer look.")
    else:
        print("NO candidate beat the champion out-of-sample -> the current config is not improvable on this data.")
        print("That's a real result: it means we're not leaving money on the table, and any 'better' in-sample")
        print("tweak was curve-fitting. Keep the champion and move to forward-testing.")


if __name__ == "__main__":
    main()
