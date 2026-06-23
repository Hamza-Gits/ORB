# SCRIPTS — the Python toolkit

Every script in `Python/`. Run all of them from inside the `Python/` folder
(`cd Python` first) after `pip install -r requirements.txt`. The master dataset
is `MNQ_full_1min.csv` (committed). See [`CHAMPION.md`](CHAMPION.md) for the
config these tools converged on.

---

## Core engine & runners

| Script | What it does |
|---|---|
| **`orb_strategy.py`** | **The engine — single source of truth for the trading logic.** Defines `Params` (every knob), `load_csv()`, `prepare_days()` (one-time per-day prep for fast grid search), `run_prepared()` (fast backtest on prepped days), `run_backtest()` (convenience: load→prep→run), and the metrics. Mirrors `FiveMinuteORB.cs`. No lookahead; same-bar stop+target resolved pessimistically (assume stop first). Contains the documented audit fixes (LA1/LA2/EX1/DST/etc.). |
| `orb_backtest.py` | CLI: run ONE backtest, print the stats table, save a trades CSV + equity-curve PNG. |
| `orb_optimize.py` | CLI: grid search + heatmap + walk-forward (`--split DATE`). The original optimizer. |
| `make_sample_data.py` | Generate synthetic but valid 1-min data to smoke-test the pipeline (P&L is meaningless). |
| `build_continuous.py` | Stitch NinjaTrader per-contract `.txt` exports (UTC, end-of-bar) into a continuous front-month 1-min series → how `MNQ_full_1min.csv` was built. Raw inputs are NOT in the repo (too large); they live in the user's local `Historical Data/`. |
| `requirements.txt` | numpy + pandas + matplotlib. |

---

## The definitive optimization (what produced the champion)

| Script | What it does |
|---|---|
| **`orb_final.py`** | The big grid optimizer. **4,860 combos** across `or_minutes` (5/10/15/30/60), `offset_ticks`, `direction`, `bias`, `max_or_points`, `regime`, and a composite `target` token (rr1.0…rr3.0 / atr1.0…atr2.5). Pass 1 = full-history grid (keep net>0, trades≥150). Pass 2 = re-run survivors on each of 5 time segments, keep all-positive, rank by worst segment. Writes `*_fullgrid.csv` and `*_robust.csv`. |
| `orb_pass2.py` | Single-threaded Pass-2 robustness (segment re-run). Slow. |
| **`orb_pass2_par.py`** | **Parallel Pass 2** — `ProcessPoolExecutor`, 7 workers, Windows-safe initializer that loads the CSV + segments once per process. Reads a saved `*_fullgrid.csv`, runs 5-segment robustness for all survivors in ~8 min (vs. ~2 h single-threaded). This produced `mnq7_all_robust.csv` (1,294 all-5-segment-positive configs). |
| **`orb_montecarlo.py`** | Block-bootstrap (block=10) Monte Carlo + **prop-eval race** simulator. For each account (25K/50K) simulates day-by-day until profit target (PASS) / EOD trailing-DD breach (BLOW) / 252 days (TIMEOUT). Models both "lock at start balance" and strict always-trailing DD. Produces the survival table in [`RESULTS.md`](RESULTS.md#monte-carlo--prop-survival). |

---

## Variable studies (how each dimension was tested)

| Script | Dimension tested | Verdict |
|---|---|---|
| `orb_width_study.py` | OR-width volatility filter | width ≤ 130 helps (cuts choppy days) |
| `orb_bias_study.py` | directional bias (ema/vwap variants) | `vwap_slope` is the key edge; VWAP > EMA |
| `orb_entry_study.py` | entry style (stop/close/rebreak/retest) | **touch/stop wins**; confirmation enters worse |
| `orb_risk_study.py` | stop modes & $-sizing | tight fixed stops hurt (whipsaw) |
| `orb_exit_study.py` | breakeven / trailing / scale-out | **trailing stops hurt** (cut the runners) |
| `orb_newvars_study.py` | misc additional variables | (exploratory) |
| `orb_robustness.py` | multi-segment stability helper (`segment_days()`) | used by the OOS scripts |
| `dd_analysis.py` | drawdown analysis (e.g. 2-contract sizing) | 2 contracts breach a $1,500 limit → 1 micro |

---

## Out-of-sample exploration (why we stopped tuning)

Both search ONLY on in-sample 2019–2023, then validate **once** on a LOCKED
2024–2026 vault. A change is real only if it beats the champion out-of-sample.
Both concluded: **no improvement exists.** See
[`PROJECT_STATE.md`](PROJECT_STATE.md#6-why-we-stopped-tuning-the-oos-discipline).

| Script | Tested | Result |
|---|---|---|
| `orb_explore_oos.py` | entry cutoff, min OR width, ADX threshold, ATR mult (108 combos) | no variant beat champion OOS |
| `orb_explore2_oos.py` | re-entry (max trades/day), day-of-week | re-entry hurts; no droppable weekday |

---

## Stat helpers (quick reporting)

| Script | Output |
|---|---|
| `_fullstats.py` | the full statistics table in [`RESULTS.md`](RESULTS.md#full-backtest-statistics) |
| `_monthly.py` | month × year P&L pivot + monthly distribution |
| `_yearly.py` | per-year trade count, win%, net (champion vs. a high-net variant) |

---

## Data & result files in the repo

| File | Contents |
|---|---|
| `MNQ_full_1min.csv` | **master dataset** — continuous MNQ 1-min, 2019–2026 (~969k bars). 57 MB. |
| `mnq7_all_fullgrid.csv` | all 4,860 combos, full-period results |
| `mnq7_all_robust.csv` | 1,294 configs profitable in all 5 segments, ranked by worst segment |
| `mnq7_final_*.csv`, `mnq_final_*.csv`, `mnq_robust*.csv` | earlier grid/robustness outputs (superseded by the `mnq7_all_*` pair but kept for the record) |
| `orb_grid.csv`, `mnq_opt_grid.csv`, `mnq_wf_train_grid.csv` | earlier optimizer grids |

**Gitignored (not in repo, regenerable / too large):** raw `Historical Data/`
`.txt` exports (~150 MB+), `MES_1min.csv` (dead end), `MNQ_1min.csv` (superseded),
`sample_MNQ_1min.csv` (synthetic), all `*_trades.csv` / `*_equity.png` /
`*_heatmap.png` per-run byproducts, and `__pycache__/`. See `.gitignore`.
