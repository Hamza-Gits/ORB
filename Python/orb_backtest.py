"""
orb_backtest.py
===============
Run ONE backtest of the 5-minute Opening Range Breakout and print the stats.

Examples
--------
    python orb_backtest.py --csv sample_MNQ_1min.csv --instrument MNQ --rr 1.5
    python orb_backtest.py --csv MES_1min.csv --instrument MES --rr 2 --or-minutes 5 \
                           --offset-ticks 1 --direction both --timestamp close

Outputs
-------
    <out>_trades.csv   every trade with entry/exit/PnL
    <out>_equity.png   cumulative net P&L curve (needs matplotlib)
"""

import argparse

from orb_strategy import INSTRUMENTS, Params, load_csv, run_backtest, format_metrics


def build_params(a) -> Params:
    return Params(
        instrument=a.instrument,
        or_start=a.or_start,
        or_minutes=a.or_minutes,
        exit_time=a.exit_time,
        rr=a.rr,
        offset_ticks=a.offset_ticks,
        direction=a.direction,
        max_trades=a.max_trades,
        contracts=a.contracts,
        commission_rt=a.commission_rt,
        slippage_ticks=a.slippage_ticks,
        pessimistic=not a.optimistic,
        min_or_points=a.min_or_points,
        max_or_points=a.max_or_points,
        bias=a.bias,
        ema_period=a.ema_period,
        bias_slope_lookback=a.bias_slope_lookback,
        entry_mode=a.entry_mode,
        stop_mode=a.stop_mode,
        stop_points=a.stop_points,
        stop_atr_mult=a.stop_atr_mult,
        stop_or_frac=a.stop_or_frac,
        atr_period=a.atr_period,
        risk_dollars=a.risk_dollars,
        max_contracts=a.max_contracts,
        regime=a.regime,
        regime_adx_min=a.regime_adx_min,
        regime_ma_period=a.regime_ma_period,
        entry_cutoff=a.entry_cutoff,
        skip_nfp=a.skip_nfp,
        skip_opex=a.skip_opex,
        breakeven_r=a.breakeven_r,
        trail_mode=a.trail_mode,
        trail_ticks=a.trail_ticks,
        trail_atr_mult=a.trail_atr_mult,
        scale_out_r=a.scale_out_r,
        scale_frac=a.scale_frac,
        vol_confirm_mult=a.vol_confirm_mult,
        fib_entry=a.fib_entry,
        rvol_min=a.rvol_min,
        rvol_period=a.rvol_period,
        gap_mode=a.gap_mode,
        gap_pct=a.gap_pct,
        target_mode=a.target_mode,
        target_atr_mult=a.target_atr_mult,
    )


def main():
    ap = argparse.ArgumentParser(description="5-minute ORB backtest (single run)")
    ap.add_argument("--csv", required=True, help="intraday OHLCV CSV (1-minute recommended)")
    ap.add_argument("--instrument", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--or-start", default="09:30", dest="or_start")
    ap.add_argument("--or-minutes", type=int, default=5, dest="or_minutes")
    ap.add_argument("--exit-time", default="15:55", dest="exit_time")
    ap.add_argument("--rr", type=float, default=1.0, help="reward:risk ratio")
    ap.add_argument("--offset-ticks", type=int, default=0, dest="offset_ticks")
    ap.add_argument("--direction", default="both", choices=["both", "long", "short"])
    ap.add_argument("--max-trades", type=int, default=1, dest="max_trades")
    ap.add_argument("--min-or-points", type=float, default=0.0, dest="min_or_points",
                    help="skip days whose opening range is narrower than this (points; 0=off)")
    ap.add_argument("--max-or-points", type=float, default=0.0, dest="max_or_points",
                    help="skip days whose opening range is wider than this (points; 0=off)")
    ap.add_argument("--bias", default="none",
                    choices=["none", "ema_slope", "ema_price", "vwap", "vwap_slope", "vdelta"],
                    help="trend filter: take only the bias-side breakout each day")
    ap.add_argument("--ema-period", type=int, default=20, dest="ema_period")
    ap.add_argument("--bias-slope-lookback", type=int, default=1, dest="bias_slope_lookback")
    ap.add_argument("--entry-mode", default="stop", dest="entry_mode",
                    choices=["stop", "close", "rebreak", "retest", "fib"],
                    help="stop=touch (default); close/rebreak/retest/fib = confirmation/pullback entries")
    ap.add_argument("--stop-mode", default="or", dest="stop_mode",
                    choices=["or", "points", "atr", "or_frac"])
    ap.add_argument("--stop-points", type=float, default=0.0, dest="stop_points")
    ap.add_argument("--stop-atr-mult", type=float, default=1.0, dest="stop_atr_mult")
    ap.add_argument("--stop-or-frac", type=float, default=1.0, dest="stop_or_frac")
    ap.add_argument("--atr-period", type=int, default=14, dest="atr_period")
    ap.add_argument("--risk-dollars", type=float, default=0.0, dest="risk_dollars",
                    help=">0 sizes contracts to a constant $ risk per trade")
    ap.add_argument("--max-contracts", type=int, default=10, dest="max_contracts")
    ap.add_argument("--regime", default="none", choices=["none", "adx", "ma"])
    ap.add_argument("--regime-adx-min", type=float, default=20.0, dest="regime_adx_min")
    ap.add_argument("--regime-ma-period", type=int, default=50, dest="regime_ma_period")
    ap.add_argument("--entry-cutoff", default="", dest="entry_cutoff",
                    help="no new entries at/after this time, e.g. 11:30")
    ap.add_argument("--skip-nfp", action="store_true", dest="skip_nfp")
    ap.add_argument("--skip-opex", action="store_true", dest="skip_opex")
    ap.add_argument("--breakeven-r", type=float, default=0.0, dest="breakeven_r")
    ap.add_argument("--trail-mode", default="none", dest="trail_mode", choices=["none", "ticks", "atr"])
    ap.add_argument("--trail-ticks", type=float, default=0.0, dest="trail_ticks")
    ap.add_argument("--trail-atr-mult", type=float, default=0.0, dest="trail_atr_mult")
    ap.add_argument("--scale-out-r", type=float, default=0.0, dest="scale_out_r")
    ap.add_argument("--scale-frac", type=float, default=0.5, dest="scale_frac")
    ap.add_argument("--vol-confirm-mult", type=float, default=0.0, dest="vol_confirm_mult")
    ap.add_argument("--fib-entry", type=float, default=0.5, dest="fib_entry",
                    help="retracement ratio for --entry-mode fib (0.5-0.618)")
    ap.add_argument("--rvol-min", type=float, default=0.0, dest="rvol_min",
                    help="require OR-window volume >= this x its trailing average (0=off)")
    ap.add_argument("--rvol-period", type=int, default=20, dest="rvol_period")
    ap.add_argument("--gap-mode", default="none", dest="gap_mode",
                    choices=["none", "skip_large", "with", "fade"])
    ap.add_argument("--gap-pct", type=float, default=0.5, dest="gap_pct")
    ap.add_argument("--target-mode", default="rr", dest="target_mode", choices=["rr", "atr"])
    ap.add_argument("--target-atr-mult", type=float, default=1.0, dest="target_atr_mult")
    ap.add_argument("--contracts", type=int, default=1)
    ap.add_argument("--commission-rt", type=float, default=1.24, dest="commission_rt",
                    help="commission per contract round-turn ($)")
    ap.add_argument("--slippage-ticks", type=int, default=1, dest="slippage_ticks")
    ap.add_argument("--optimistic", action="store_true",
                    help="resolve same-bar stop+target as target (default is pessimistic=stop)")
    ap.add_argument("--tz", default="America/New_York", help="analysis timezone (cash-open reference)")
    ap.add_argument("--source-tz", default=None, dest="source_tz",
                    help="timezone the file is actually in (e.g. UTC for raw NinjaTrader exports)")
    ap.add_argument("--timestamp", default="open", choices=["open", "close"],
                    help="open = bar start-stamped (most CSVs); close = NinjaTrader exports")
    ap.add_argument("--out", default="orb", help="output file prefix")
    args = ap.parse_args()

    df = load_csv(args.csv, tz=args.tz, source_tz=args.source_tz, timestamp=args.timestamp)
    print(f"Loaded {len(df):,} bars  "
          f"{df.index.min()}  ->  {df.index.max()}")

    p = build_params(args)
    trades, m = run_backtest(df, p)

    print("\n========== 5-MINUTE ORB RESULTS ==========")
    print(format_metrics(m, p))
    print("==========================================\n")

    trades_path = f"{args.out}_trades.csv"
    trades.to_csv(trades_path, index=False)
    print(f"Saved {len(trades)} trades -> {trades_path}")

    # equity curve (optional)
    if len(trades):
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            eq = trades["net"].cumsum()
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(trades["entry_time"].values, eq.values)
            ax.set_title(f"{p.instrument} 5-min ORB  |  RR {p.rr}  |  net ${m['net']:,.0f}")
            ax.set_ylabel("Cumulative net P&L ($)")
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            png = f"{args.out}_equity.png"
            fig.savefig(png, dpi=110)
            print(f"Saved equity curve -> {png}")
        except ImportError:
            print("(matplotlib not installed -> skipped equity curve)")


if __name__ == "__main__":
    main()
