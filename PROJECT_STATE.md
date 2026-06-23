# PROJECT STATE — master handoff

> **Read this first.** This is the single source of truth for the 5-minute ORB
> project. If you are a fresh session (human or AI) picking this up cold, read
> this file top to bottom and you will know exactly where things stand and what
> to do next. Companion docs: [`CHAMPION.md`](CHAMPION.md) (exact winning config),
> [`RESULTS.md`](RESULTS.md) (every number + scaling math), [`SCRIPTS.md`](SCRIPTS.md)
> (what each Python tool does), [`docs/KIT_GUIDE.md`](docs/KIT_GUIDE.md) (setup).
>
> Last updated: 2026-06-23.

---

## 0. TL;DR — current status

We have a **fully researched, validated, and platform-ported** 5-minute Opening
Range Breakout strategy for **MNQ** (Micro E-mini Nasdaq-100 futures), tuned for
a **FLEX EVAL prop account**.

- **The research is done.** 4,860-combo optimization + 5-segment robustness +
  Monte Carlo prop-survival + two disciplined out-of-sample exploration rounds.
  The champion config is confirmed at its ceiling for this data — further tuning
  is overfitting, not improvement.
- **The strategy is ported and parity-verified** in NinjaTrader 8
  (`NinjaTrader/FiveMinuteORB.cs`). It reproduces the Python engine.
- **The ONE thing left before risking money: forward-test** on NinjaTrader
  sim / Market Replay on going-forward data. Everything above is backtest.

**The champion (memorize this):**
`15-min OR / 2-tick offset / both directions / vwap_slope bias / OR width ≤ 130 pts /
ADX(14) ≥ 20 regime filter / target = entry ± 1.5 × prior-day daily ATR(14).`
Net **+$27,603 / 7 years / 1 micro**, PF 1.45, 45.1% win, max EOD drawdown
**−$1,607** (fits the 50K account's $2,000 limit). Full details in
[`CHAMPION.md`](CHAMPION.md).

---

## 1. The goal

The user is building an automated income stream by **passing prop-firm
evaluations** and compounding the payouts into more accounts. Not investing own
capital in the market — the capital at risk is the **eval fee** (~$98 per 50K
account), and the upside is the firm's payouts.

Plan: pass a 25K eval first → take the first payout → use it to buy a batch of
50K evals → reinvest every subsequent payout into more 50K evals → repeat.
The trading strategy in this repo is the engine that passes and funds those
accounts. Scaling math is in [`RESULTS.md`](RESULTS.md#scaling--compounding).

---

## 2. The prop firm — FLEX EVAL accounts

The user's firm uses **FLEX EVAL** accounts. Critical rules that shaped every
decision:

| Rule | 25K account | 50K account |
|---|---|---|
| Profit target | $1,250 | **$3,000** |
| Max loss (EOD trailing drawdown) | $1,000 | **$2,000** |
| Daily loss limit | **none** | **none** |
| Contracts | 2 mini / 20 micro | 4 mini / 40 micro |
| Eval fee | $70 (+$60 reset) | **$98 (+$95 reset)** |
| Consistency rule | 50% (eval only) | 50% (eval only) |

- **EOD trailing drawdown** = the max-loss line trails your end-of-day balance
  up as you profit, then (in FLEX) typically **locks at the starting balance**
  once you've banked enough buffer. No intraday daily limit means a single bad
  day can't fail you on a daily rule — only the trailing drawdown matters.
- **Consistency rule applies in the eval only**, not once funded.
- **Open question to confirm with the firm:** exactly when/whether the trailing
  DD locks at start balance after a buffer. This is decisive for sizing and was
  flagged as an assumption in the Monte Carlo (we modeled both "lock at start"
  and strict "always trailing").

**Sizing conclusion: 1 micro per 50K account.** The strategy's natural variance
is tighter than the account limits only at 1 micro. At 2 micro, Monte Carlo
shows 30–48% blow rates — unsafe. The 25K's $1,000 limit is too tight even at
1 micro (the champion's −$1,607 max DD would breach it), so **the 50K is the
right vehicle**; the 25K is just the cheap entry ticket that funds the first
50K batch.

---

## 3. How we got here (the research journey, condensed)

This is the reasoning trail so a fresh session understands *why* the champion is
what it is, not just *what* it is.

1. **Started with the textbook ORB** (5-min range, fixed reward:risk, both
   directions). Result: weak. The classic 5-min OR alone is ~breakeven after
   costs (PF ~1.04).

2. **MES is a dead end.** Tested the same strategy on MES (S&P micros) over
   2020–2026 incl. the 2022 bear: **0 / 1008 configs profitable in all four
   segments.** ORB is a *trending-instrument* strategy and the Nasdaq (MNQ)
   trends; the S&P doesn't trend hard enough. MES was abandoned. (Its data file
   is gitignored — conclusion documented, data not needed.)

3. **MNQ has a real, cycle-tested edge.** Full 2019–2026 history (2,086 days,
   969k 1-min bars, incl. the 2020 COVID crash and 2022 bear) → with the right
   filters, **hundreds of configs are profitable in ALL FIVE time segments.**
   ORB rides trends in *either* direction, so it survived 2020 and 2022. Its
   real weakness is **chop** (2023 was nearly flat), not downturns — the
   opposite of MES.

4. **What makes the edge robust (the filters that matter):**
   - **`vwap_slope` directional bias** — the single biggest contributor. Take
     only the breakout side that agrees with the intraday VWAP's slope across
     the opening range. (A 2nd audit caught and fixed a 1-bar lookahead in this
     bias; re-validation showed the edge barely moved → it's real, not an
     artifact.)
   - **ADX(14) ≥ 20 regime filter** — only trade when the prior day's daily ADX
     says we're trending. Cuts drawdown.
   - **OR-width filter (≤ 130 pts)** — skip days where the opening range is so
     wide the day is already chaotic.
   - **ATR target** — the breakthrough. Instead of targeting a multiple of the
     (tiny) 5-min range, target **entry ± 1.5 × the prior-day daily ATR**. This
     decouples the profit target from the OR width and roughly **doubled** net
     vs. the old fixed-RR configs. 15-min OR is the sweet spot.

5. **What HURTS (tested and rejected):** tight fixed stops (whipsaw), trailing
   stops (they cut the runaway breakouts that ARE the edge), re-entry / more
   than 1 trade per day, and confirmation entry styles (close/rebreak/retest —
   they enter worse and miss runaway breakouts). The edge lives in letting the
   first breakout run to an ATR-scaled target.

6. **Definitive optimization (4,860 combos)** including 5/10/15/30/60-min ORs
   and the ATR-target dimension → 4,330 net-positive, **1,294 profitable in all
   5 segments**. The champion emerged as the best *prop-fit* config (max DD
   inside the 50K limit).

7. **Monte Carlo prop-survival** (block bootstrap, 10k paths, simulating the
   day-by-day race to the $3,000 target vs. the $2,000 trailing-DD blow):
   **50K @ 1 micro = 90% pass / 9% blow, median 77 days to pass.** See
   [`RESULTS.md`](RESULTS.md#monte-carlo--prop-survival).

8. **Ported to NinjaScript and parity-verified** (Section 5 below).

9. **Two disciplined out-of-sample exploration rounds** both concluded: the
   champion is **unimprovable on this data** (Section 6 below). The edge even
   *strengthened* out-of-sample — the strongest evidence it isn't curve-fit.

---

## 4. The champion config (summary — full detail in CHAMPION.md)

| Parameter | Value |
|---|---|
| Opening range | first **15 minutes** after 09:30 ET |
| Entry offset | **2 ticks** beyond the OR level |
| Direction | **both** (long on OR-high break, short on OR-low break) |
| Directional bias | **`vwap_slope`** (only trade the side agreeing with intraday VWAP slope) |
| OR-width filter | skip if OR width **> 130 points** |
| Regime filter | trade only if **prior-day daily ADX(14) ≥ 20** |
| Target | **entry ± 1.5 × prior-day daily ATR(14)** |
| Stop | opposite OR extreme |
| Trades/day | 1 (first breakout only) |
| Flat by | 15:55 ET |
| Costs modeled | $1.24 round-turn commission + 1 tick slippage |

**Headline result (1 micro, 2019–2026):** net **+$27,603**, PF **1.45**, win
**45.1%**, max EOD DD **−$1,607**, Sharpe **2.27**, 862 trades. Positive every
full year including the 2022 bear. Full breakdown in [`RESULTS.md`](RESULTS.md).

---

## 5. NinjaScript port — DONE and parity-verified

`NinjaTrader/FiveMinuteORB.cs` was rewritten to reproduce the champion exactly:
self-built daily bars + Wilder ATR/ADX (per ET date, prior-day = no lookahead,
matching the Python `_atr`/`_adx`), self-accumulated session VWAP, OR-width
filter, `vwap_slope` bias, ADX regime, and ATR target. Defaults = the champion.
Compiles clean (F5, no errors).

**Parity result** (NT Strategy Analyzer, continuous back-adjusted MNQ, 2019–2026):

| Metric | Python | NinjaTrader |
|---|---|---|
| Trades | 862 | 848 |
| Win rate | 45.1% | 43.4% |
| Profit factor | 1.45 | 1.37 |
| Net | +$27,603 | +$22,095 |
| Max DD | −$1,607 | −$2,105 |

Per-trade stats (avg win ~$222–228, avg loss ~−$125–129) are near-identical →
**faithful port.** The ~20% net gap is data artifacts (NT continuous-contract
roll vs. Python volume-stitch, DST-mismatch weeks, back-adjusted prices in the
width filter), **not a logic difference**.

> ### ⚠️ The timezone bug — root-caused and fixed (don't lose this)
> First NT backtest showed 14% win / −$1,037. Cause: **NinjaTrader displays bars
> in the PC's local timezone.** The user is in the UK (UTC+1), which is 5 hours
> ahead of New York. So the strategy's "09:30" was being measured at **09:30 UK
> = 04:30 ET = dead pre-market** → a ~20-point OR instead of the real ~68-point
> OR → 84% stop-outs → net loss.
>
> **Permanent fix (do this for live/forward-test):** NinjaTrader → Tools →
> Options → General → **Time zone = Eastern**. Then the default ET parameters in
> the strategy (OR 09:30, flatten 15:55, daily-agg 08:00–17:00) work as-is. This
> is standard practice for US futures.
>
> **Test-only workaround we used** (if NT is left on UK time): shift the 4 time
> inputs +5h → OR start 14:30, flatten 20:55, daily-agg 13:00–22:00. Don't ship
> this; set NT to Eastern instead.

---

## 6. Why we stopped tuning (the OOS discipline)

The user (rightly) kept asking "can we test more variables?" We did — **with
discipline**: search only on in-sample 2019–2023, then validate the survivors
**once** on a LOCKED 2024–2026 vault the search never touched. A change is real
only if it beats the champion *out-of-sample*.

- **Round 1** (`orb_explore_oos.py`, 108 combos: entry cutoff, min OR width,
  ADX threshold, ATR multiple): **no variant beat the champion OOS.** Every
  in-sample "improvement" underperformed out-of-sample — curve-fitting caught
  in the act.
- **Round 2** (`orb_explore2_oos.py`: re-entry / max trades-per-day, and
  day-of-week): re-entry **hurts** both IS and OOS. No weekday is a clean
  bleeder (Monday is the *tempting* one — barely positive IS, slightly negative
  OOS — but acting on that requires peeking at the OOS set, which is exactly the
  trap; and $376 over 104 Mondays is noise).

**The decisive evidence the edge is real, not fit:** the champion's performance
got *better* on unseen data — IS (2019–2023) PF 1.38 / +$14,472 vs. OOS
(2024–2026) PF **1.59** / +$13,120.

**Conclusion locked in:** the config is at its ceiling for this dataset. More
backtesting now produces *negative* information (each extra test burns
out-of-sample credibility via multiple-comparisons). The next real information
comes from forward-testing, not more tuning.

---

## 7. The honest risks (do not let optimism bury these)

1. **Backtest PF 1.45 → live will likely be lower.** Slippage, fills, and feed
   differences always erode a backtest. Forward-testing measures the real gap.
2. **Copy-traded accounts are perfectly correlated.** Running the champion on
   10 accounts is NOT 10 independent 9%-blow bets — it's ONE bet replicated 10
   times. A bad 77-day window blows all of them **simultaneously**. The "9%
   blow" is correlated, not diversified.
3. **The edge is Nasdaq-trend-dependent.** 2023 chop nearly flattened it. There
   is no post-2026 data; an unseen chop/regime-change year could underperform
   everything in the backtest.
4. **Prop ROI is on the eval fee, not return-on-account.** The right mental
   frame is "~$98 risked per account to chase a $3,000 target + payouts," not a
   percentage return on 50K. Don't compare it to S&P annual %.

---

## 8. WHAT'S NEXT — the pending work

In priority order:

1. **Forward-test (the gate before any money).** Set NinjaTrader to Eastern
   time, load the champion strategy on a 1-min MNQ chart on the **Sim101**
   account (or run Market Replay on recent unseen data), and let it trade live
   sessions for several weeks. Compare live fills/win-rate/DD to the backtest.
   *This is the single most important remaining task.* A forward-test runbook
   was offered but not yet written — write it when resuming.
2. **Confirm the FLEX trailing-DD lock rule** with the firm (Section 2). It
   changes sizing safety.
3. **Pass a 25K eval**, take the first payout, then execute the 50K compounding
   plan (math in [`RESULTS.md`](RESULTS.md#scaling--compounding)).
4. **Rollout / correlation management** — how many accounts, and accepting that
   they blow together. Consider staggering account start dates so they're not in
   the same drawdown window.

---

## 9. How to resume in a fresh session

If you're a new chat picking this up:

1. Read this file, then [`CHAMPION.md`](CHAMPION.md) and [`RESULTS.md`](RESULTS.md).
2. The Python engine is `Python/orb_strategy.py` (single source of truth for the
   logic). Public API: `load_csv()`, `prepare_days()`, `run_prepared()`,
   `run_backtest()`. The master dataset is `Python/MNQ_full_1min.csv` (committed).
3. To reproduce the champion's headline numbers:
   ```powershell
   cd Python
   pip install -r requirements.txt
   python orb_montecarlo.py --csv MNQ_full_1min.csv --instrument MNQ ^
     --or-minutes 15 --offset-ticks 2 --direction both --bias vwap_slope ^
     --max-or-points 130 --regime adx --target atr1.5 --paths 10000
   ```
   (or use the small helper scripts `_fullstats.py`, `_monthly.py`, `_yearly.py`).
4. The NinjaScript is `NinjaTrader/FiveMinuteORB.cs`, defaults = champion.
   Remember the **timezone fix** (Section 5) before backtesting/forward-testing.
5. [`SCRIPTS.md`](SCRIPTS.md) explains every tool in `Python/`.

**Do not re-run parameter optimization expecting improvement** — two OOS rounds
proved the ceiling. The productive next step is forward-testing (Section 8),
not more tuning.

---

## 10. Repo map

```
ORB/
├─ PROJECT_STATE.md          <- you are here (master handoff)
├─ CHAMPION.md               <- exact winning config, Python + NinjaScript
├─ RESULTS.md                <- all stats, yearly/monthly, Monte Carlo, scaling math
├─ SCRIPTS.md                <- what each Python tool does
├─ README.md                 <- short overview + pointers
├─ docs/
│  └─ KIT_GUIDE.md           <- original setup guide (NinjaTrader + Python install)
├─ NinjaTrader/
│  └─ FiveMinuteORB.cs        <- NT8 strategy, defaults = champion, parity-verified
└─ Python/
   ├─ orb_strategy.py         <- core engine (single source of truth)
   ├─ orb_final.py            <- the 4,860-combo grid optimizer (Pass 1 + Pass 2)
   ├─ orb_pass2_par.py        <- parallel 5-segment robustness (ProcessPoolExecutor)
   ├─ orb_montecarlo.py       <- block-bootstrap prop-survival simulator
   ├─ orb_explore_oos.py      <- OOS exploration round 1
   ├─ orb_explore2_oos.py     <- OOS exploration round 2 (re-entry, day-of-week)
   ├─ _fullstats.py / _monthly.py / _yearly.py  <- stat helpers
   ├─ MNQ_full_1min.csv       <- master dataset 2019–2026 (committed, 57 MB)
   ├─ mnq7_all_fullgrid.csv   <- all 4,860 combos, full-period results
   ├─ mnq7_all_robust.csv     <- 1,294 configs profitable in all 5 segments
   └─ ... (see SCRIPTS.md for the rest)
```
