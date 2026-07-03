# CONTEXT — live continuity file

> **Purpose.** This file is an anti-amnesia backup against context-window
> compaction. If you are a fresh chat picking this project up, treat this file as
> a **PRIMARY source of truth alongside your live context window** — read it in
> full, then cross-reference [`PROJECT_STATE.md`](PROJECT_STATE.md) (deep master
> handoff), [`CHAMPION.md`](CHAMPION.md), [`RESULTS.md`](RESULTS.md),
> [`SCRIPTS.md`](SCRIPTS.md). Nothing here should be re-derived or re-litigated;
> it is settled. Use BOTH this file and your window so there are no gaps.
>
> **Last updated:** 2026-07-01.

---

## 1. One-paragraph orientation

The user has a **fully researched, validated, and platform-ported 5-minute
Opening Range Breakout (ORB) strategy for MNQ** (Micro E-mini Nasdaq-100 futures),
built to pass **FLEX EVAL prop-firm accounts** and compound the payouts. The
research phase is **DONE** (7 years of data, 4,860-combo optimization, 5-segment
robustness, Monte-Carlo prop survival, two out-of-sample rounds — the config is
at its ceiling; **do not re-optimize**). We are now in the **validation /
forward-test phase**: proving the edge holds going forward and, right now,
**helping the user verify it by hand** to build personal confidence before
risking money.

---

## 2. The champion config (memorize — this is THE strategy)

`15-min OR (09:30–09:45 ET) / 2-tick offset / both directions filtered by
vwap_slope bias / skip if OR width > 130 pts / trade only if prior-day daily
ADX(14) ≥ 20 / target = entry ± 1.5 × prior-day daily ATR(14) / stop = opposite
OR extreme / 1 trade per day / flat by 15:55 ET.`

- Costs modeled: **$1.24 round-turn commission + 1-tick slippage.** MNQ = **$2/point**, tick = 0.25 pt.
- **Headline (1 micro, 2019–2026, post-audit clean data): +$27,025 net, PF 1.44, 44.1% win, max EOD DD −$1,769** (fits the 50K account's $2,000 limit). 836 trades. (Pre-audit figures were 862 / +$27,603 / −$1,607 — see §3f.)
- **Sizing: 1 micro per 50K account** (Monte Carlo: ~90% pass / 9% blow; STATIC 2 micro blows 30–48% — unsafe; buffer-based scaling after banking profit is the safe way up, §3e).
- **~1-year return ≈ 8–9% of a 50K account per micro** (~$4,300/yr avg of the 6 full backtest years; Monte-Carlo median ~$3,650 ≈ 7%). Backtested, not guaranteed.
- Per-year net/micro: 2020 +$3.5k, 2021 +$5.0k, 2022 +$4.4k (bear), 2023 +$1.7k (chop, its weakest regime), 2024 +$4.6k, 2025 +$5.7k, 2026-YTD +$2.4k, 2019 partial −$0.2k.
- **Why it works:** win rate is only ~42–45% but wins are far bigger than the capped losses. Losses ≈ OR width × $2 (stop = opposite OR extreme). Winners ride to the 15:55 flatten. The ATR target (~600–1,300 pts) is almost never hit intraday — most winners are profitable 15:55 exits, not target hits. **The edge = small capped losses + letting winners run to the bell.** Do NOT add trailing stops or tighter stops — tested, they kill it.

---

## 3. What happened in the latest session (the live developments)

### 3a. NinjaTrader free-feed backtest failure — ROOT-CAUSED (do not re-diagnose)
The user's NT Strategy Analyzer runs on **MNQ SEP26** (Jan–Jun 2026) looked
catastrophic (−$2,712 / 10% win) even after fixing the timezone. Fully diagnosed
(see [`PROJECT_STATE.md`](PROJECT_STATE.md) **Section 5b**): the cause is **contract
month**, not the strategy. SEP26 was the **thin back-month** contract for that whole
window (front until JUN26 expired 2026-06-19; SEP26 became liquid front only
~2026-06-11). Thin liquidity **compressed the opening range to ⅓ its true width**
(NT ~33 pts vs Python ~88 pts) while daily ATR matched — so stops sat hair-trigger
tight → 88% stop-out. **Python (clean continuous `MNQ_full_1min.csv`) is the
source of truth for history; never trust an NT backtest on a back-month/thin
free-feed contract.** Diagnostic scripts: `Python/_nt_deepdive_run3.py`,
`_nt_orderlevels.py`, `_nt_compare_2026.py`; evidence in `Back Test Results/3/`.

### 3b. Forward-testing questions — ANSWERED
- **Keeping it running unattended:** run FifteenMinuteORB as a **live strategy on
  Sim101** (1-min front-month chart, **Days-to-load = 120** (calendar days — see
  §3h; 40 is too few), Calculate=On bar close, Enabled). It then trades every
  session automatically, flat overnight. NT must stay open+connected and the PC
  awake — or run NT on a **VPS** for true 24/7.
- **10-min delayed free feed — VERDICT:** **FINE for sim forward-testing.** The
  delay is a uniform clock-shift; bars carry real timestamps/prices and Sim101
  fills against the same delayed stream, so sim P&L faithfully measures the edge.
  It is NOT valid for **live money** (orders would post ~10 min after the OR
  closes, missing fast breakouts) — but the actual **prop eval runs on the firm's
  real-time data**, so that concern is moot when it matters.

### 3c. The user found NT too hard to set up → we built a MANUAL toolkit (this session's deliverables)
Because NinjaTrader was fighting the user and they wanted to validate the strategy
with their own eyes, we built:

- **`Manual Tester/ORB_Manual_Tester.html`** — a self-contained browser calculator
  (double-click to open, no install). Inputs: **OR width in points** (user
  measures it themselves), prior-day ADX, prior-day ATR (optional), VWAP slope
  (up/down). It applies all the champion gates live, shows TRADE/NO-TRADE + the
  side + risk, then logs each day (outcome: never-filled / hit-stop / ran-to-15:55)
  with running **win% / net P&L / profit factor**. Saves to browser localStorage;
  CSV export. **Note:** an earlier version took OR High + OR Low; the user asked
  to simplify to a single width input — current version is width-only (it can't
  print exact entry/stop prices from width alone, so for live levels the user
  supplies the OR High and we compute Entry = ORHigh+0.50, Stop = ORLow−0.50,
  Target = Entry ± 1.5×ATR).
- **`Manual Tester/orb_answer_key.csv`** — the "answer key": all **836 champion
  trades** (regenerated after the 2026-07-02 data audit, §3f) with date, side,
  or_width, prior_adx, entry_et, exit, points, net, cum_net. Lets the user
  spot-check their manual reads against the real engine instead of grinding
  every day by hand. Regenerate with **`Python/_answer_key.py`**.

### 3d. The user began verifying by hand — and it MATCHED
- Verified **2026-04-15**: after correcting a measurement mistake (they first
  measured 424 pts by reading into the next day's peak), the true entry→15:55
  read was **~294–308 pts**, matching the engine's **+294 pts / +$587**. ✅
- **CRITICAL measuring rule (state this if they get big numbers):** winners are
  measured from entry to the **15:55 close**, NOT to the day's high/peak; losers
  are just the stop (the tool computes it from width). Measuring to the peak
  inflates every trade and creates false confidence.
- We handed the user four more days to check independently:
  **2026-04-13** (long, w~65, +$563), **2026-04-06** (long, w~128, stop −$261),
  **2026-05-13** (short, w~109, stop −$222), **2026-06-16** (short, w~110, +$717).
  As of the handoff, the user is working through these.

### 3e. Returns-improvement research (2026-07-01) — DONE, do not redo the signal part
The user asked to improve returns. **Signal re-tuning was NOT reopened** (grid
re-audit confirmed: only the champion's own atr2.5 twin beats it inside the DD
cap, by a noise-level +$490/7yr, and ATR-mult changes already failed OOS).
Instead we built **`Python/_scaling_mc.py`** — a session-clock Monte Carlo of the
full FLEX account lifecycle (eval → funded → blow → new eval), with buffer-based
contract scaling, payout sweeps, eval fees/resets, and the 50% consistency rule.
Verified: closed-form fee cross-checks, anchors vs `orb_montecarlo.py`, seed
stability, determinism. Findings (10k paths, block=21 over 1,823 RTH sessions):

1. **The old "median 77 days to pass" was mis-clocked** — `orb_montecarlo.py`
   counts *trades* as days. True figure at 1 micro ≈ **244 calendar days**
   (only ~70% pass within a year). RESULTS.md scaling math was ~3× optimistic
   on cycle speed.
2. **Eval at 2 micros dominates**: blow rate rises ~9%→33%, but a blown eval
   costs only the $95 reset. Campaign (repeat-until-pass): median **123 days
   & $142 total fees** vs 259 days & $107 at 1 micro. 3 micros: 91d/$172
   (consistency rule starts binding ~13% of passes; modeled).
3. **Funded scaling ladder**: contracts = 1 per $2,000 of headroom above the
   MLL, cap 3–5, extract profits via Lucid payout cycles. Scale-downs in
   drawdowns actually LOWER death risk vs static-1 (0.06→0.02 deaths/yr).
4. **The firm rules are CONFIRMED (Lucid support, 2026-07-01)** — 50K
   LucidFlex: MLL trails EOD balance at −$2,000 until a close above $52,100,
   then **locks at $50,100 forever** (withdrawals do NOT move it — the lock
   the whole scaling case depended on is REAL). Payouts: 5 days of ≥$150
   each per cycle → request 50% of profit up to $2,000 (min $500), **90/10
   split**, no funded consistency rule, 40-micro cap both stages.
5. **Final numbers (all Lucid rules modeled, income post-90/10-split, net of
   fees, per 50K slot, 5-yr lifecycle sim, post-audit clean data):** current
   plan (eval@1 + funded static 1) **≈$2,650/yr**; eval@2 + cap-3 ladder
   **≈$5,450/yr (2.1×)**; eval@2 + cap-5 ladder **≈$9,000/yr (3.4×)** — with
   better 5th-percentile and fewer deaths. Caveat: the $2,000/payout cap
   throttles cash extraction (~$7k/yr cash at cap-5; the rest accrues as
   account balance, credited at 90% in these totals). Verified by adversarial
   review + independent from-scratch reproduction (all headline numbers
   within MC noise).

### 3f. Full data + engine audit (2026-07-02) — PASSED, with one data fix
Pre-forward-test audit of the engine, data, and overfitting evidence:
- **Engine (`orb_strategy.py`): clean.** Line-by-line review found no lookahead
  (OR/bias/regime/target all decided at OR close or from day i−1), pessimistic
  same-bar stop-first resolution, costs correct. Headline reproduced to the
  penny pre-fix (862 / $27,603.12 / PF 1.4512 / −$1,606.92).
- **Data fix:** `MNQ_full_1min.csv` had ONE corrupt bar (2024-01-20, a
  SATURDAY, open/low = 0.50 vs market ≈17,463, volume 6) whose fake 17,463-pt
  daily range poisoned Wilder ADX for weeks → wrongly admitted 32 extra trades
  in Feb–May 2024 (+$978). It also had 903 weekend administrative-print bars
  (volume ≤ 8, no real trading; the dataset is day-session 08:00–17:00 only)
  forming fake stub "days" in the daily ATR/ADX series (96/862 trades had a
  weekend stub as their "prior day"). **All weekend bars removed** from the
  CSV and `build_continuous.py` now filters them on rebuild. Exhaustive scans
  (rolling-median outliers, fat-finger ranges, intraday jumps) found nothing
  else — every other outlier is a real event (CPI 08:30 bars, COVID, 2025-04).
- **Clean baseline: 836 trades / +$27,025 / PF 1.44 / win 44.1% / maxDD
  −$1,769 / worst 3-mo −$1,314.** Answer key regenerated (the user's five
  manual spot-check trades are IDENTICAL). IS→OOS improved: PF 1.37 → 1.62.
- **Overfitting checks: passed.** Champion sits on a parameter plateau (or 10m
  ≈ 91% of champion net; targets atr1.0–2.5 within ±2%; offsets 0–2 flat; the
  filters help but the strategy is profitable without them). OOS strengthens.
  Honest caveats: `vwap_slope` is the one load-bearing discrete choice (validated
  across 5 segments + OOS), and Sharpe should be quoted as **1.50**
  (calendar) not 2.27 (trade-days-only inflation).
- Grid CSVs (`mnq7_all_*.csv`) and the §5 NT parity table are pre-audit
  artifacts — fine for relative comparisons, don't quote absolute nets.

### 3g. Pre-2019 NQ test (2026-07-02) — THE EDGE IS ERA-DEPENDENT (critical)
The user bought nothing: he exported **NQ 2015–2018 per-contract 1-min data
from NinjaTrader** (MNQ didn't exist yet; NQ = same index, so `instrument="MNQ"`
on NQ prices gives the exact per-micro equivalent). `build_continuous.py`
stitched it (`Python/NQ_2015_2018_1min.csv`, 532,673 bars, 1,031 sessions,
audit battery CLEAN). The **frozen champion** (zero re-tuning) on it:

- **PF 0.94, net −$737 over 4 years, win 38.9%, 3 of 4 years negative**
  (2015 +$442, 2016 −$341, 2017 −$189, 2018 −$650). Costs ≈ $1,064 of the
  loss → gross edge ≈ zero, not negative. maxDD −$1,582 (slow bleed, no crater).
- **Conclusion: the edge is NOT timeless.** It turned on ~2019–2020 (micro
  launch / 0DTE era / post-COVID intraday dynamics — cause unproven). The
  2024–26 OOS validation still proves it isn't curve-fit *within* the modern
  era; this proves the modern era itself is the bet.
- **No simple gate detects the regime**: intraday-vol (OR% of price) correlates
  only 0.43 with yearly P&L — 2018 had MORE vol than 2024/2025 yet lost. The
  regimes differ in breakout FOLLOW-THROUGH, whose only reliable symptom is
  the strategy's own P&L.
- **What separates the eras: persistence of losing windows.** Rolling
  126-session P&L was negative in **64%** of windows in 2015–18 vs **7%**
  in 2019–26 (worst single window: −$593 dead era vs −$747 live era — depth
  does NOT separate, persistence does).
- **PRE-REGISTERED stand-down rule (protection, not tuning):** if the rolling
  6-month champion P&L (live + sim combined) stays **negative for 3
  consecutive month-ends → stop buying evals, go sim-only**; resume when the
  rolling 6-month sim P&L turns positive. In-era calibration; forward data
  validates it. Failure-mode cost if the regime dies ≈ a few months of eval
  fees, not blown capital.
- 2026 YTD (+$2,421, healthy) says the regime is ON as of June 2026. The
  forward test now does double duty: execution check + live regime reading.
- **Do NOT re-tune the champion on 2015–18 to "fix" it** — that would be
  fitting the strategy to a market that no longer exists.

### 3h. Forward test LIVE on Sim101 (2026-07-03) — running + OR-parity confirmed
The user got `FifteenMinuteORB` (renamed from FiveMinuteORB; class name kept
stable) running live on **Sim101**, 1-min **MNQ SEP26** chart. Added **v1.1**:
per-session decision logging to the NinjaScript Output window (SKIP + reason /
TRADEABLE + levels / FILLED). Both the repo copy and the user's install copy
(`Documents/NinjaTrader 8/bin/Custom/Strategies/`) are updated; the old
`FiveMinuteORB.cs` there was renamed to `.bak`.

- **OR-width parity CONFIRMED live.** NT's logged SEP26 opening-range widths
  match the Python engine's continuous front-month widths **to the decimal**
  (06-12 237.8=237.8, 06-15 133.8=133.8, 06-17 130.3≈130.2, 06-18 223.0=223.0,
  06-22 169.8=169.8; 06-16 & 06-19 both ≤130 in both). → timezone is correct,
  SEP26 data is clean (no §5b compression), NT reproduces the engine. This is
  the core forward-test check and it PASSED on OR measurement.
- **Heavy filtering is correct, not a bug.** June 2026 was a genuinely wide-range
  month — our own data shows **88% of June days had OR width >130** (median 156).
  So the strategy standing down almost every June day is the width filter working
  as designed. Other 2026 months skip 24–62%. Expect the **first live trade to be
  a week or two out** while volatility is elevated; the log proves it's evaluating
  correctly meanwhile.
- **⚠️ Days-to-load fix.** NT "Days to load" is CALENDAR days. ADX needs ~29
  TRADING days (~41 calendar) just to warm up, so the earlier "≥40" guidance was
  too low — 50 nearly all went to warmup (~20 "ADX warming up" lines). **Use
  Days-to-load = 120** so ADX is robustly warm + a month of margin at every
  restart. (Strategy is warm now at ~35 days, but a restart on 50 could relapse.)
- Runbook essentials that held up: timezone = Eastern (implied correct by the
  parity match), Calculate=On bar close, Account=Sim101, Enabled ✓, front month
  = SEP26 (roll to DEC26 ~2026-09-10).

---

## 4. Gotchas & facts that MUST NOT be lost

1. **Data-source drift is expected and OK.** TradingView / NT free feeds are a
   different contract series than `MNQ_full_1min.csv`. Indicator *values* drift
   (e.g. on 2026-04-15 the user's chart ADX read 36.72 vs the engine's 22.7), but
   the **decisions match** (both clear ≥20). Do not panic when a value isn't a
   pixel-perfect match — check that the trade/no-trade outcome agrees.
2. **Front month = SEP26 now; roll to DEC26 ~2026-09-10.** MNQ is quarterly
   (Mar/Jun/Sep/Dec, 3rd-Friday expiry, volume rolls ~1 week prior).
3. **NT timezone MUST be the DST-aware named zone** "(UTC-05:00) Eastern Time
   (US & Canada)" — never a fixed UTC-4/UTC-5 offset (can't span the DST switch).
4. **Python interpreter trap:** on this machine `python` may resolve to **3.14,
   which has NO numpy/pandas**. Use Python **3.12**:
   `C:\Users\hamza\AppData\Local\Programs\Python\Python312\python` (has numpy 2.5.0 / pandas 3.0.3).
5. **Manual tester friction model:** stop-out net = −(width+1)×2 − $2.24 (comm +
   2-tick slip); 15:55 exit net = points×2 − $1.74 (comm + 1-tick slip). These
   reconcile with `orb_strategy.py`.
6. The strategy is **flat overnight** — it only acts 09:30–15:55 ET.

---

## 5. The user — who they are & how to work with them

- Building an **automated prop-eval income stream** (FLEX EVAL accounts; capital
  at risk = the ~$98 eval fee, not market capital). Plan: pass a 25K eval → use
  the payout to buy 50K evals → compound. See [`RESULTS.md`](RESULTS.md) scaling math.
- **Not deeply technical.** Struggles with NinjaTrader setup; strongly prefers
  simple, manual, visual tools (hence the browser calculator).
- **Cautious about false confidence** — wants to verify with his own eyes before
  trusting the backtest. Honor that; give him ways to check, not just assertions.
- On a **free 10-min-delayed feed** (hasn't paid for live data; Tradovate personal
  demo wanted paid data, prop-firm login had no demo). Timezone references have
  been confusing (UK-ish / UTC offset mix-ups) — **always anchor times to ET**.
- **Prefers concise answers**; gets frustrated by over-explanation and by
  processes that "take ages." Lead with the answer.

---

## 6. Open items / next steps (in priority order)

1. ~~Confirm the FLEX trailing-DD lock rule with the firm~~ **DONE 2026-07-01**
   (user asked Lucid support; answers in Section 3e item 4 — lock is real,
   scaling is viable).
2. **Finish the manual spot-check** (optional confidence): a few more days from
   the answer key vs the user's chart. If they keep matching, validation is done.
3. **Real forward test** — either let FifteenMinuteORB run live on **Sim101** from
   now, or keep manually stepping through history with the tester. This is the
   gate before any money (and before acting on any Section-3e upgrade).
4. **Pass a 25K eval → execute the 50K compounding plan** — with the Section-3e
   upgrades: **evals at 2 micros; funded = 1 micro per $2,000 headroom, cap
   3–5**.
5. Remember the **correlated-risk caveat**: copy-trading N accounts is one bet
   replicated N times; a bad stretch blows them together. Stagger start dates.

---

## 7. The honest risks (carry these forward, do not let optimism bury them)

1. Backtest PF 1.44 → **live will likely be lower** (slippage/fills erode it).
2. **Copy-traded accounts are perfectly correlated** — the 9% blow rate is not diversified.
3. The edge is **era-dependent, not just trend-dependent** — §3g proved it did
   NOT exist in 2015–2018 (PF 0.94). The plan is a bet that the post-2019
   intraday regime persists; the stand-down rule (§3g) caps the cost if it dies.
4. **Prop ROI is on the eval fee, not return-on-account** — don't frame it as an S&P-style % return (except when the user explicitly asks for the account-% figure, which is ~9%).

---

## 8. Repo map (key files)

```
ORB/
├─ CONTEXT.md                 <- THIS FILE — live continuity, read first
├─ PROJECT_STATE.md           <- master handoff (deep). Section 5b = NT free-feed trap
├─ CHAMPION.md / RESULTS.md / SCRIPTS.md / README.md
├─ Manual Tester/
│  ├─ ORB_Manual_Tester.html  <- browser calculator (width-based, logs + stats)
│  └─ orb_answer_key.csv      <- all 836 champion trades + running P&L
├─ Back Test Results/         <- raw NT exports (evidence); /3 = the Section-5b run
├─ NinjaTrader/FifteenMinuteORB.cs  <- NT8 strategy, defaults = champion, parity-verified
└─ Python/
   ├─ orb_strategy.py         <- core engine (single source of truth)
   ├─ _answer_key.py          <- regenerates orb_answer_key.csv
   ├─ _nt_deepdive_run3.py / _nt_orderlevels.py / _nt_compare_2026.py  <- NT-vs-Py forensics
   ├─ MNQ_full_1min.csv       <- master dataset 2019–2026 (source of truth, committed)
   └─ ... (see SCRIPTS.md)
```

**Bottom line for the next chat:** the strategy is done and validated; we are
helping the user *believe* it by verifying trades by hand with the browser tool +
answer key, and lining up a Sim101 forward test. Pick up at Section 6.
