# Kit setup guide (NinjaTrader + Python)

> This is the original beginner-oriented setup guide for the kit — how to install
> NinjaTrader 8 and Python, get data, and run the tools. For the **current state
> of the research and the champion config**, see
> [`../PROJECT_STATE.md`](../PROJECT_STATE.md) and [`../CHAMPION.md`](../CHAMPION.md)
> instead. The strategy spec below describes the *original* textbook ORB; the
> project has since evolved the rules (15-min OR, vwap_slope bias, ADX regime,
> ATR target) — `CHAMPION.md` has the final version.

---

## 1. The exact strategy rules (original textbook version)

| Item | Rule |
|------|------|
| Opening range | High & Low of the first **5 minutes** after the 09:30 ET open (configurable) |
| Direction | **Whichever side breaks first** (long *or* short) |
| Long entry | Buy-stop at the **OR high** |
| Short entry | Sell-stop at the **OR low** |
| Stop loss | The **opposite** side of the range (long → OR low, short → OR high) |
| Target | **Reward:Risk × range** — start at **1:1**, then test **1.5:1** and **2:1** |
| Trades/day | First breakout only (1), configurable |
| End of day | Force-flat at **15:55 ET**, hard safety net at the session close |

**Risk = the size of the opening range** (OR high − OR low).

---

## 2. What to download (and where)

### A. NinjaTrader 8 — free
- **https://ninjatrader.com** → *Get Started / Free Download*.
- The free license gives unlimited **simulation trading, charting, backtesting,
  and optimization** — everything needed here. You only pay to go live.
- Install, create the free account, open the **Control Center**.

### B. Python 3 — free
- On Windows the Microsoft Store stub `python` does not work well. Install the
  real one from **https://www.python.org/downloads/** → Python 3.12 → tick
  **"Add python.exe to PATH"**. Verify in a new PowerShell: `python --version`.

### C. Market data
You need **1-minute intraday history** for MNQ. Easiest sources:
1. **From NinjaTrader** once you connect a data feed (then export to CSV).
2. **FirstRate Data** (firstratedata.com) — free samples, cheap full history.
3. **Databento / Polygon.io** — paid, high quality.

> The project's master dataset (`Python/MNQ_full_1min.csv`, 2019–2026) is already
> committed, built by `build_continuous.py` from NinjaTrader per-contract exports.

---

## 3. Quick start — prove the pipeline works

From the `Python` folder:

```powershell
cd Python
pip install -r requirements.txt
python make_sample_data.py --instrument MNQ --days 120 --out sample_MNQ_1min.csv
python orb_backtest.py --csv sample_MNQ_1min.csv --instrument MNQ --rr 1.5
python orb_optimize.py --csv sample_MNQ_1min.csv --instrument MNQ --objective net
```

If a results table prints and a `*_trades.csv` appears, you're good. **Sample
data is random — ignore the P&L.**

---

## 4. Using NinjaTrader

### 4.1 Add the strategy
1. Control Center → *New → NinjaScript Editor*.
2. Copy `NinjaTrader/FifteenMinuteORB.cs` into
   `Documents\NinjaTrader 8\bin\Custom\Strategies\`, then press **F5** to compile.
3. A green "build successful" = done.

### 4.2 Get data into NinjaTrader
- Connect a feed (a free brokerage demo — Tradovate / AMP / NT Continuum demo).
- Open a **1-minute chart** of front-month **MNQ ##-##**; NT downloads history.
- **Set the chart/platform time zone to Eastern**: *Tools → Options → General →
  Time zone → (UTC-05:00) Eastern.* **This is mandatory** — see the timezone bug
  writeup in [`../PROJECT_STATE.md`](../PROJECT_STATE.md#5-ninjascript-port--done-and-parity-verified).

### 4.3 Backtest (Strategy Analyzer)
1. Control Center → *New → Strategy Analyzer*.
2. Pick **MNQ**, the date range, **1 Minute** bars.
3. Strategy → **FifteenMinuteORB** (defaults already = the champion config).
4. Realism settings: **Order Fill Resolution = High (1-tick)**, **Commission**
   ~$1.24 round-turn, **Slippage** 1 tick.
5. **Run**, review Summary / Trades / Chart.

### 4.4 Forward test on the simulator
- Drag **FifteenMinuteORB** onto a live 1-min MNQ chart, enable on **Sim101**, and
  let it run live sessions for several weeks. **This is the real test before any
  money** (see PROJECT_STATE.md §8).

---

## 5. Using the Python backtester

```powershell
# single run
python orb_backtest.py --csv MNQ_full_1min.csv --instrument MNQ --rr 1.5 --or-minutes 5 --offset-ticks 1 --direction both

# grid search + heatmap
python orb_optimize.py --csv MNQ_full_1min.csv --instrument MNQ --objective profit_factor

# walk-forward (optimize on older data, verify on newer)
python orb_optimize.py --csv MNQ_full_1min.csv --instrument MNQ --split 2024-07-01
```

### Key flags
| Flag | Meaning | Default |
|------|---------|---------|
| `--instrument` | MNQ / MES / NQ / ES (sets tick value) | MNQ |
| `--rr` | reward:risk | 1.0 |
| `--or-minutes` | opening-range length | 5 |
| `--offset-ticks` | extra ticks to confirm the break | 0 |
| `--direction` | both / long / short | both |
| `--commission-rt` | round-turn commission per contract ($) | 1.24 |
| `--slippage-ticks` | slippage on stop fills | 1 |
| `--timestamp` | `open` (most CSVs) or `close` (NinjaTrader exports) | open |

---

## 6. Optimization principles (kept us honest)

1. **Look for a plateau, not a peak** — a region of good settings is real; a
   lone spike is noise.
2. **Demand enough trades** (`--min-trades 30`+).
3. **Always walk-forward / out-of-sample** — anything you'd trade must survive
   data the search never saw. (This project went further: a fully LOCKED
   2024–2026 vault. See PROJECT_STATE.md §6.)
4. **Keep costs in** — never optimize with zero commission/slippage.
5. **Profit factor and max drawdown matter more than net profit.**

---

## 7. Known limitations

- **Intrabar ambiguity** — with 1-min OHLC we can't always know if stop or target
  hit first inside a bar; the engine assumes the **stop** (pessimistic).
- **Both-side gap days** — if price blows through both OR extremes in one bar,
  fills are approximated; the offset reduces this.
- **Continuous vs. front-month** — backtest on the actual contract or a properly
  back-adjusted series; raw stitched data can distort the range on roll days.
- **NinjaScript ≈ Python but not tick-identical** — use NT's Strategy Analyzer as
  the authority on fills, Python for fast parameter exploration. (Parity was
  verified — see PROJECT_STATE.md §5.)
