# CHAMPION — the exact winning configuration

The one config to trade. Selected from a 4,860-combo grid by **cross-segment
robustness** (profitable in all 5 time segments) AND **fitting the 50K account's
$2,000 EOD drawdown limit** — not by max net profit. See
[`PROJECT_STATE.md`](PROJECT_STATE.md) for the reasoning and
[`RESULTS.md`](RESULTS.md) for full statistics.

---

## The rules in plain English

1. After the **09:30 ET** open, mark the **High and Low of the first 15 minutes**
   (the opening range, "OR").
2. Only consider trading if **prior-day daily ADX(14) ≥ 20** (we're trending) and
   the **OR width ≤ 130 points** (the day isn't already chaos).
3. Decide the allowed side from **VWAP slope**: if the intraday session VWAP rose
   across the opening range → **longs only**; if it fell → **shorts only**.
4. Place a stop-entry **2 ticks beyond** the allowed side's OR level (buy-stop
   above OR high, or sell-stop below OR low).
5. **Stop loss** = the opposite OR extreme. **Target** = entry ± **1.5 × the
   prior-day daily ATR(14)** (long: entry + 1.5·ATR; short: entry − 1.5·ATR).
6. **One trade per day.** Force flat by **15:55 ET**.

---

## Python parameters (`orb_strategy.py` → `Params`)

```python
from dataclasses import replace
from orb_strategy import Params, load_csv, prepare_days, run_prepared

base = Params(instrument="MNQ", commission_rt=1.24, slippage_ticks=1)
champion = replace(base,
    or_minutes      = 15,           # 15-minute opening range
    offset_ticks    = 2,            # enter 2 ticks beyond the level
    direction       = "both",       # long OR short, whichever side is allowed
    bias            = "vwap_slope", # VWAP-slope directional filter
    max_or_points   = 130.0,        # skip days with OR width > 130 pts
    regime          = "adx",        # ADX regime filter ...
    regime_adx_min  = 20.0,         #   ... require prior-day daily ADX(14) >= 20
    target_mode     = "atr",        # ATR-scaled target ...
    target_atr_mult = 1.5,          #   ... entry +/- 1.5 x prior-day daily ATR(14)
    atr_period      = 14,
)
df   = load_csv("MNQ_full_1min.csv", tz="America/New_York")
days = prepare_days(df)
trades, metrics = run_prepared(days, champion)
print(metrics)   # net ~ +$27,025, PF ~ 1.44, win ~ 44.1%, maxDD ~ -$1,769
                 # (post-2026-07-02 data audit; see RESULTS.md)
```

Everything not listed is the engine default (stop = opposite OR extreme,
`max_trades=1`, `exit_time="15:55"`, `entry_mode="stop"`, `or_start="09:30"`).

---

## NinjaScript parameters (`NinjaTrader/FifteenMinuteORB.cs`)

The strategy's **defaults already equal the champion** — drop it on a chart and
it trades this config. The mapping:

| NinjaScript input | Value | Python equivalent |
|---|---|---|
| `OrMinutes` | 15 | `or_minutes=15` |
| `OffsetTicks` | 2 | `offset_ticks=2` |
| `Direction` | Both | `direction="both"` |
| `Bias` | VwapSlope | `bias="vwap_slope"` |
| `MaxOrPoints` | 130.0 | `max_or_points=130.0` |
| `UseAdxRegime` | true | `regime="adx"` |
| `AdxMin` | 20.0 | `regime_adx_min=20.0` |
| `AdxPeriod` | 14 | (ADX period) |
| `TargetMode` | Atr | `target_mode="atr"` |
| `TargetAtrMult` | 1.5 | `target_atr_mult=1.5` |
| `AtrPeriod` | 14 | `atr_period=14` |
| `OrStartTime` | 093000 | `or_start="09:30"` |
| `FlattenTime` | 155500 | `exit_time="15:55"` |
| `DailyAggStartTime` | 080000 | daily-bar window start (08:00) |
| `DailyAggEndTime` | 170000 | daily-bar window end (17:00) |

> **⚠️ Timezone:** the time inputs above are **Eastern**. NinjaTrader displays
> bars in the PC's local timezone, so you MUST set NinjaTrader → Tools → Options
> → General → **Time zone = Eastern** for these to be correct. The user is in the
> UK; without this fix the "09:30 OR" is measured at 04:30 ET (pre-market) and
> the strategy loses money. See [`PROJECT_STATE.md`](PROJECT_STATE.md#5-ninjascript-port--done-and-parity-verified)
> for the full root-cause writeup. (Self-built daily ATR/ADX and session VWAP are
> inside the strategy so it does not depend on NT session templates.)

---

## CLI one-liner (Monte Carlo + headline stats)

```powershell
cd Python
python orb_montecarlo.py --csv MNQ_full_1min.csv --instrument MNQ ^
  --or-minutes 15 --offset-ticks 2 --direction both --bias vwap_slope ^
  --max-or-points 130 --regime adx --target atr1.5 --paths 10000
```

Note the composite `--target atr1.5` token: the optimizer encodes the target as
one string (`atr1.5` → `target_mode="atr"`, `target_atr_mult=1.5`; `rr2.0` →
`target_mode="rr"`, `rr=2.0`).

---

## Higher-return sibling (NOT prop-safe — for reference)

Same core but `regime="none"` and `target_atr_mult=2.5` → net **+$36,142**,
PF 1.39 (pre-audit grid figures; see RESULTS.md audit note), but max DD
**−$3,212** which **breaks the 50K's $2,000 limit**. Only
viable on a larger/own-capital account or a churn-many-accounts approach. The
prop-fit champion above is the one to actually trade on FLEX evals.
