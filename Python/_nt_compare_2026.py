"""
Ad-hoc: reproduce the champion on the FULL dataset (proper warmup from 2019),
then isolate Jan 1 - Jun 23 2026 to compare against the NinjaTrader SEP26 backtest
(61 trades, 9.84% win, -$2,747). Same window, same rules.
"""
import pandas as pd
from orb_strategy import Params, load_csv, run_backtest

df = load_csv("MNQ_full_1min.csv", tz="America/New_York", source_tz=None, timestamp="open")
print(f"Loaded {len(df):,} bars  {df.index.min()} -> {df.index.max()}")

p = Params(
    instrument="MNQ",
    or_start="09:30",
    or_minutes=15,
    exit_time="15:55",
    offset_ticks=2,
    direction="both",
    max_trades=1,
    max_or_points=130,
    bias="vwap_slope",
    regime="adx",
    regime_adx_min=20,
    atr_period=14,
    target_mode="atr",
    target_atr_mult=1.5,
    commission_rt=1.24,
    slippage_ticks=1,
    contracts=1,
)

trades, m = run_backtest(df, p)

def summarize(t, label):
    n = len(t)
    if n == 0:
        print(f"\n[{label}] no trades")
        return
    wins = t[t["net"] > 0]
    losses = t[t["net"] <= 0]
    print(f"\n========== {label} ==========")
    print(f"Trades:        {n}")
    print(f"Win rate:      {len(wins)/n*100:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"Net:           ${t['net'].sum():,.2f}")
    print(f"Avg win:       ${wins['net'].mean():,.2f}" if len(wins) else "Avg win: --")
    print(f"Avg loss:      ${losses['net'].mean():,.2f}" if len(losses) else "Avg loss: --")
    if "exit_reason" in t.columns:
        print("Exit reasons:")
        print(t["exit_reason"].value_counts().to_string())

# Validate full-period reproduces the known champion numbers
summarize(trades, "FULL 2019-2026 (should be ~862 trades / +$27,603)")

# Isolate the NinjaTrader comparison window
et = pd.to_datetime(trades["entry_time"])
mask = (et >= pd.Timestamp("2026-01-01", tz="America/New_York")) & \
       (et <= pd.Timestamp("2026-06-23", tz="America/New_York"))
sub = trades[mask].copy()
summarize(sub, "2026-01-01 .. 2026-06-23 (NT window: 61 trades / 9.84% / -$2,747)")

print("\nColumns available:", list(trades.columns))

# Dump every Python 2026 trade so we can diff vs the NT 61-trade list
pd.set_option("display.max_rows", None)
pd.set_option("display.width", 200)
sub2 = sub.copy()
sub2["day"] = pd.to_datetime(sub2["entry_time"]).dt.strftime("%d/%m/%Y")
sub2["etime"] = pd.to_datetime(sub2["entry_time"]).dt.strftime("%H:%M")
print("\n--- PYTHON 2026 TRADES (the 24 it actually took) ---")
print(sub2[["day", "etime", "direction", "or_high", "or_low", "range_pts", "reason", "net"]].to_string(index=False))

# ---- CONTROLLED TEST: cold-start Python on Jan 1 2026 (no warmup), like NT did ----
df_cold = df[df.index >= pd.Timestamp("2026-01-01", tz="America/New_York")]
trades_cold, m_cold = run_backtest(df_cold, p)
etc = pd.to_datetime(trades_cold["entry_time"])
mask_c = (etc >= pd.Timestamp("2026-01-01", tz="America/New_York")) & \
         (etc <= pd.Timestamp("2026-06-23", tz="America/New_York"))
summarize(trades_cold[mask_c], "2026 COLD-START (no warmup, mimics NT's Jan-1 data start)")
firstc = pd.to_datetime(trades_cold["entry_time"]).min()
print(f"\nCold-start first trade date: {firstc}  (NT's first trade was 13/02/2026)")

