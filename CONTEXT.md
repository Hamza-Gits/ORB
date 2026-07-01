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
- **Headline (1 micro, 2019–2026): +$27,603 net, PF 1.45, 45.1% win, max EOD DD −$1,607** (fits the 50K account's $2,000 limit).
- **Sizing: 1 micro per 50K account** (Monte Carlo: 90% pass / 9% blow; 2 micro blows 30–48% — unsafe).
- **~1-year return ≈ 9% of a 50K account per micro** (~$4,500/yr avg of the 6 full backtest years; Monte-Carlo median ~$3,900 ≈ 8%). Backtested, not guaranteed.
- Per-year net/micro: 2020 +$4.3k, 2021 +$4.4k, 2022 +$5.3k (bear), 2023 +$1.1k (chop, its weakest regime), 2024 +$5.7k, 2025 +$6.2k, 2026-YTD +$1.2k, 2019 partial −$0.6k.
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
- **Keeping it running unattended:** run FiveMinuteORB as a **live strategy on
  Sim101** (1-min front-month chart, Days-to-load ≥ 40, Calculate=On bar close,
  Enabled). It then trades every session automatically, flat overnight. NT must
  stay open+connected and the PC awake — or run NT on a **VPS** for true 24/7.
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
- **`Manual Tester/orb_answer_key.csv`** — the "answer key": all **862 champion
  trades** with date, side, or_width, prior_adx, entry_et, exit, points, net,
  cum_net. Lets the user spot-check their manual reads against the real engine
  instead of grinding every day by hand. Regenerate with **`Python/_answer_key.py`**.

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

1. **Finish the manual spot-check** (optional confidence): a few more days from
   the answer key vs the user's chart. If they keep matching, validation is done.
2. **Real forward test** — either let FiveMinuteORB run live on **Sim101** from
   now, or keep manually stepping through history with the tester. This is the
   gate before any money.
3. **Confirm the FLEX trailing-DD lock rule** with the firm (when/if the drawdown
   line locks at start balance after a buffer) — decisive for sizing safety.
4. **Pass a 25K eval → execute the 50K compounding plan.**
5. Remember the **correlated-risk caveat**: copy-trading N accounts is one bet
   replicated N times; a bad stretch blows them together. Stagger start dates.

---

## 7. The honest risks (carry these forward, do not let optimism bury them)

1. Backtest PF 1.45 → **live will likely be lower** (slippage/fills erode it).
2. **Copy-traded accounts are perfectly correlated** — the 9% blow rate is not diversified.
3. The edge is **Nasdaq-trend-dependent**; 2023 chop nearly flattened it; an unseen regime could underperform.
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
│  └─ orb_answer_key.csv      <- all 862 champion trades + running P&L
├─ Back Test Results/         <- raw NT exports (evidence); /3 = the Section-5b run
├─ NinjaTrader/FiveMinuteORB.cs  <- NT8 strategy, defaults = champion, parity-verified
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
