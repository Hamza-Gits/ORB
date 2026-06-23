"""
orb_explore2_oos.py
===================
Second, genuinely-NEW variable exploration -- still OOS-disciplined.
Search/inspect on IN-SAMPLE 2019-2023, validate on the LOCKED 2024-2026 vault.

  A) Re-entry: max trades per day (1 vs 2 vs 3)
  B) Day-of-week filter: is any weekday a consistent bleeder?

A change is real only if it beats the champion OUT-OF-SAMPLE.
"""

from dataclasses import replace
import numpy as np
import pandas as pd
from orb_strategy import Params, load_csv, prepare_days, run_prepared, run_backtest

OOS_START = pd.Timestamp("2024-01-01").date()
CHAMP = dict(or_minutes=15, offset_ticks=2, direction="both", bias="vwap_slope",
             max_or_points=130.0, regime="adx", regime_adx_min=20.0,
             target_mode="atr", target_atr_mult=1.5)
WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def split(days):
    return ([d for d in days if d["date"] < OOS_START],
            [d for d in days if d["date"] >= OOS_START])


def net_pf(days, p):
    _, m = run_prepared(days, p)
    return m["net"], m["profit_factor"], m["win_rate"], m["max_drawdown"], m["trades"]


def main():
    df = load_csv("MNQ_full_1min.csv", tz="America/New_York")
    days = prepare_days(df)
    is_d, oos_d = split(days)
    base = Params(instrument="MNQ", commission_rt=1.24, slippage_ticks=1)
    champ = replace(base, **CHAMP)

    ci, co = net_pf(is_d, champ), net_pf(oos_d, champ)
    print(f"CHAMPION   IS net ${ci[0]:>8,.0f} PF {ci[1]:.2f}  |  OOS net ${co[0]:>8,.0f} PF {co[1]:.2f}  DD ${co[3]:,.0f}\n")

    # ---------- A) Re-entry: max trades/day ----------
    print("A) RE-ENTRY (max trades per day)")
    print(f"   {'maxTr':>5} | {'IS net':>8} {'IS PF':>5} | {'OOS net':>8} {'OOS PF':>6} {'OOS DD':>8}")
    print("   " + "-"*52)
    for mt in (1, 2, 3):
        p = replace(champ, max_trades=mt)
        i, o = net_pf(is_d, p), net_pf(oos_d, p)
        flag = "  <-- beats champ OOS" if (mt != 1 and o[0] > co[0]) else ""
        print(f"   {mt:>5} | {i[0]:>8,.0f} {i[1]:>5.2f} | {o[0]:>8,.0f} {o[1]:>6.2f} {o[3]:>8,.0f}{flag}")

    # ---------- B) Day-of-week ----------
    tr, _ = run_backtest(df, champ)
    tr["dt"] = pd.to_datetime(tr["date"])
    tr["wd"] = tr["dt"].dt.weekday
    tr["oos"] = tr["dt"].dt.date >= OOS_START
    is_tr, oos_tr = tr[~tr["oos"]], tr[tr["oos"]]

    print("\nB) DAY-OF-WEEK  (champion's per-weekday net)")
    print(f"   {'day':>4} | {'IS trades':>9} {'IS net':>9} {'IS win%':>8} | {'OOS net':>9}")
    print("   " + "-"*48)
    is_by = is_tr.groupby("wd")["net"].agg(["size", "sum", lambda x: (x > 0).mean()*100])
    oos_by = oos_tr.groupby("wd")["net"].sum()
    weak_is = []
    for wd in range(5):
        n = is_by.loc[wd, "size"] if wd in is_by.index else 0
        s = is_by.loc[wd, "sum"] if wd in is_by.index else 0.0
        w = is_by.loc[wd, "<lambda_0>"] if wd in is_by.index else 0.0
        os_ = oos_by.get(wd, 0.0)
        if s < 0:
            weak_is.append(wd)
        print(f"   {WD[wd]:>4} | {n:>9.0f} {s:>9,.0f} {w:>7.1f}% | {os_:>9,.0f}")

    # test excluding the weekday(s) that lost money IN-SAMPLE, validate OOS
    print("\n   Exclusion test (drop weekdays that bled IN-SAMPLE, then check OOS):")
    if weak_is:
        keep = [w for w in range(5) if w not in weak_is]
        is_excl = is_tr[is_tr["wd"].isin(keep)]["net"].sum()
        oos_excl = oos_tr[oos_tr["wd"].isin(keep)]["net"].sum()
        names = "+".join(WD[w] for w in weak_is)
        print(f"   drop {names}:  IS net ${is_excl:,.0f} (was ${ci[0]:,.0f})  |  "
              f"OOS net ${oos_excl:,.0f} (champ ${co[0]:,.0f})  "
              f"{'<-- beats champ OOS' if oos_excl > co[0] else '<-- WORSE/equal OOS'}")
    else:
        print("   No weekday lost money in-sample -> nothing to exclude.")

    print("\n" + "="*60)
    print("Verdict: a change is only real if it beats the champion OUT-OF-SAMPLE.")


if __name__ == "__main__":
    main()
