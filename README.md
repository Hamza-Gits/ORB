# 5-Minute Opening Range Breakout (ORB) — MNQ

A complete, researched, and platform-ported Opening Range Breakout trading
system for **MNQ** (Micro E-mini Nasdaq-100 futures), tuned to pass **FLEX EVAL
prop-firm accounts** and compound the payouts.

> **This repo is a full project handoff.** Everything researched, every result,
> the exact winning config, and the code are here. A fresh session can read the
> docs below and pick up exactly where the work stopped.

---

## Status: research done — forward-test is the only thing left

- ✅ Strategy researched, optimized (4,860 combos), and robustness-tested across
  5 market segments incl. the 2020 crash and 2022 bear.
- ✅ Monte Carlo prop-survival simulated (50K @ 1 micro = **90% pass**).
- ✅ Ported to NinjaTrader 8 (`NinjaTrader/FiveMinuteORB.cs`) and **parity-verified**.
- ✅ Two disciplined out-of-sample rounds confirm the config is **unimprovable**
  on this data (the edge even *strengthened* out-of-sample).
- ✅ Full account-lifecycle simulated (eval → funded → payouts → blow → repeat)
  against the **firm's rules, confirmed directly with support**. A buffer-based
  contract-scaling plan gets **2–3.4× the income** of trading a flat 1 micro
  forever, with a *better* downside — same edge, smarter account management.
- ⏳ **Pending: forward-test** on NinjaTrader sim / Market Replay before risking
  any money. This is the next task.

**The champion:** `15-min OR / 2-tick offset / both directions / vwap_slope bias /
OR width ≤ 130 / ADX(14) ≥ 20 / target = entry ± 1.5 × prior-day ATR(14)` →
**+$27,603 / 7 yr / 1 micro**, PF 1.45, max drawdown −$1,607 (fits the 50K limit).

---

## The numbers, at a glance

### The edge (backtest, 2019–2026, 862 trades, 1 micro contract)

| Stat | Value |
|---|---|
| Win rate | 45.1% (389W / 473L) |
| Avg win vs. avg loss | $228 vs. $129 (wins run **1.8×** bigger — this is the whole edge) |
| Profit factor | 1.45 |
| Sharpe | 2.27 |
| Net profit | **+$27,603** |
| Worst historical 3-month stretch | −$933 |
| Max historical drawdown | −$1,607 (fits inside the 50K account's $2,000 limit) |
| Positive years | every full calendar year on record, incl. the 2022 bear |
| Chance any given year is a net loser | ≈4% (and small even then) |

### Risk — what can actually go wrong

| Risk | Old plan (static 1 micro) | New plan (2-micro eval + scaled funded) |
|---|---|---|
| Blow a single eval attempt (cost: $95 reset) | 8% | 31% (but passes ~2× faster overall) |
| Median time to get funded (retry-until-pass) | 257 days | **120 days** |
| Blow the funded account within year 1 | 7.8% | **6.5%** (scaling only adds size on top of banked, protected profit) |
| Full-cycle "restart from scratch" rate | 1 in ~17 slot-years | 1 in ~50 slot-years |

The 50K account's $2,000 max-loss line **locks permanently** once the balance
closes above $52,100 (confirmed directly with the prop firm, Lucid) — after
that the account cannot be blown below breakeven. The historical strategy has
never even approached the $2,000 limit (worst stretch: −$933).

### Projected income per 50K account (5-year Monte Carlo, net of fees & split)

| Plan | Avg $/yr | Bad-year (5th %ile) $/yr |
|---|---|---|
| Old: static 1 micro throughout | ~$2,700 | ~$1,050 |
| **New: 2-micro evals + funded scaling ladder (cap 5)** | **~$9,300** | **~$1,900** |

Full derivation, the simulator (`Python/_scaling_mc.py`), and the adversarial
verification of every number: [`CONTEXT.md` §3e](CONTEXT.md).

---

## Read these in order

1. **[`PROJECT_STATE.md`](PROJECT_STATE.md)** — master handoff. The full story,
   the reasoning, the risks, and what to do next. **Start here.**
2. **[`CHAMPION.md`](CHAMPION.md)** — the exact winning config, in both Python and
   NinjaScript terms, with reproduction commands.
3. **[`RESULTS.md`](RESULTS.md)** — every statistic: full/yearly/monthly, Monte
   Carlo survival, and the account-compounding math.
4. **[`SCRIPTS.md`](SCRIPTS.md)** — what each Python tool does.
5. **[`docs/KIT_GUIDE.md`](docs/KIT_GUIDE.md)** — install/setup (NinjaTrader + Python).

---

## Quick reproduce

```powershell
cd Python
pip install -r requirements.txt
python orb_montecarlo.py --csv MNQ_full_1min.csv --instrument MNQ ^
  --or-minutes 15 --offset-ticks 2 --direction both --bias vwap_slope ^
  --max-or-points 130 --regime adx --target atr1.5 --paths 10000
```

The master dataset `Python/MNQ_full_1min.csv` (MNQ 1-min, 2019–2026) is committed,
so this runs out of the box.

For the account-scaling / risk numbers above:

```powershell
cd Python
python _scaling_mc.py --paths 10000
```

---

## ⚠️ Two things not to forget

- **NinjaTrader timezone:** set Tools → Options → General → **Time zone = Eastern**
  before backtesting/forward-testing, or the "09:30 OR" is measured in pre-market
  and the strategy loses money. Full writeup in `PROJECT_STATE.md` §5.
- **Correlation risk:** running the champion on many accounts is one bet
  replicated, not many independent bets — they blow together. `RESULTS.md` §scaling.

---

*Not financial advice. Everything here is backtest/simulation until the
forward-test proves the live edge. Trade on a simulator until your own testing
convinces you.*
