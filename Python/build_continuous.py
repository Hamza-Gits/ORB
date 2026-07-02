"""
build_continuous.py
===================
Stitch a folder of NinjaTrader per-contract exports (e.g. `MNQ 09-25.Last.txt`,
`MNQ 12-25.Last.txt`, ...) into ONE continuous front-month 1-minute CSV that the
backtester can read directly.

How the roll is handled
-----------------------
For every calendar day we keep the bars of whichever contract traded the most
VOLUME that day. That is the "front month" by definition, and it rolls itself
forward automatically as liquidity migrates to the next contract -- no hard-coded
roll dates needed. Because the ORB resets every day and never holds overnight,
no price back-adjustment is required: each day is self-contained.

Timezone
--------
NinjaTrader exports are (by default) in UTC. We convert to US/Eastern so 09:30
means the cash open, and write the output already in ET start-of-bar form.

Usage
-----
    python build_continuous.py --symbol MNQ --dir "../Historical Data" --out MNQ_1min.csv
    python build_continuous.py --symbol MES --dir "../Historical Data" --out MES_1min.csv

If your export is NOT in UTC, pass --source-tz (e.g. "America/New_York" or
"America/Chicago"). Verify by checking that the printed cash-open sanity line
shows the 09:30-09:35 ET opening range on a normal weekday.
"""

import argparse
import glob
import os

import pandas as pd

from orb_strategy import load_csv


def main():
    ap = argparse.ArgumentParser(description="Stitch NinjaTrader contract files into a continuous series")
    ap.add_argument("--symbol", required=True, help="MNQ / MES / ES / NQ")
    ap.add_argument("--dir", required=True, help="folder containing the .Last.txt exports")
    ap.add_argument("--source-tz", default="UTC", dest="source_tz",
                    help="timezone the exports are in (NinjaTrader default is UTC)")
    ap.add_argument("--tz", default="America/New_York", help="analysis timezone")
    ap.add_argument("--timestamp", default="close", choices=["open", "close"],
                    help="NinjaTrader minute exports are end-of-bar -> 'close'")
    ap.add_argument("--session-start", default="08:00", dest="session_start")
    ap.add_argument("--session-end", default="17:00", dest="session_end")
    ap.add_argument("--full", action="store_true",
                    help="keep all 24h bars instead of trimming to the session window")
    ap.add_argument("--min-day-volume", type=float, default=0.0, dest="min_day_volume",
                    help="drop days whose chosen contract traded less than this volume "
                         "(removes illiquid stale-contract days during coverage gaps)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pattern = os.path.join(args.dir, f"{args.symbol} *.Last.txt")
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"No files match: {pattern}")

    print(f"Found {len(files)} {args.symbol} contract files. Loading...")
    frames = []
    for fp in files:
        name = os.path.basename(fp).replace(".Last.txt", "")
        contract = name.split(" ", 1)[1] if " " in name else name
        d = load_csv(fp, tz=args.tz, source_tz=args.source_tz, timestamp=args.timestamp)
        d = d.copy()
        d["contract"] = contract
        frames.append(d)
        print(f"  {name:16s} {len(d):>8,} bars   {d.index.min()}  ->  {d.index.max()}")

    allbars = pd.concat(frames).sort_index()
    allbars["date"] = allbars.index.date

    # ---- front month = contract with the most volume that day ----
    vol = allbars.groupby(["date", "contract"])["volume"].sum().reset_index()
    best = vol.sort_values("volume").drop_duplicates("date", keep="last")
    front = best.set_index("date")["contract"].to_dict()

    # Drop coverage-gap days where even the most-active contract is illiquid (stale roll).
    dropped = 0
    if args.min_day_volume > 0:
        liquid = set(best[best["volume"] >= args.min_day_volume]["date"])
        dropped = len(front) - len(liquid)
        front = {d: c for d, c in front.items() if d in liquid}
        print(f"\nDropped {dropped} low-liquidity day(s) below {args.min_day_volume:,.0f} volume "
              f"(coverage gaps / stale contracts).")

    keep = allbars[allbars["contract"] == allbars["date"].map(front)].copy()
    keep = keep[keep["date"].isin(front)]
    keep = keep[~keep.index.duplicated(keep="first")].sort_index()

    # ---- trim to a session window for speed (covers any sane ORB open/exit) ----
    if not args.full:
        keep = keep.between_time(args.session_start, args.session_end, inclusive="both")

    # ---- drop weekend bars (2026-07-02 audit): there is no real CME trading in
    # this session window on Sat/Sun — only sporadic volume<=8 administrative
    # prints (plus one corrupt 0.50-price bar on 2024-01-20). Left in, they form
    # fake stub "days" inside the daily ATR/ADX series used by the regime filter.
    keep = keep[keep.index.weekday < 5]

    # ---- roll report ----
    print("\nFront-month coverage (auto-detected rolls):")
    span = {}
    for date, c in sorted(front.items()):
        if c not in span:
            span[c] = [date, date]
        span[c][1] = date
    for c, (d0, d1) in sorted(span.items(), key=lambda kv: kv[1][0]):
        print(f"  {args.symbol} {c}:  {d0}  ->  {d1}")

    # ---- write canonical CSV: naive ET, start-of-bar, with header ----
    out = keep[["open", "high", "low", "close", "volume"]].copy()
    naive = out.index.tz_localize(None)
    out.insert(0, "timestamp", naive.strftime("%Y-%m-%d %H:%M:%S"))
    out.to_csv(args.out, index=False)

    n_days = len(set(keep.index.date))
    print(f"\nWrote {len(out):,} bars over {n_days} trading days -> {args.out}")
    print(f"Range: {keep.index.min()}  ->  {keep.index.max()}")

    # ---- sanity: show one mid-sample weekday's opening range so you can eyeball the tz ----
    one = keep.between_time("09:30", "09:35", inclusive="left")
    if len(one):
        days = sorted(set(one.index.date))
        day0 = days[len(days) // 2]
        d = one[one.index.date == day0]
        print(f"\nSanity check -- 09:30-09:35 ET opening range on {day0}:")
        print(f"  bars: {len(d)}   OR high: {d['high'].max()}   OR low: {d['low'].min()}")
        print("  (expect ~5 one-minute bars at the cash open; if so, the timezone is correct)")


if __name__ == "__main__":
    main()
