"""
_scaling_mc.py — buffer-based contract-scaling Monte Carlo for the FLEX prop plan.

WHY THIS EXISTS
---------------
orb_montecarlo.py answers "does 1 fixed micro survive an eval?"  It does NOT:
  * use a real session clock — it consumes one TRADE per simulated "day", so
    its "252 days" is really 252 trades (~2 calendar years) and its
    "median 77 days to pass" is 77 TRADE-days (~7.5 calendar months);
  * model the FUNDED stage at all (no account death, no payout sweeps);
  * model the eval 50%% consistency rule (provably can't bind at 1 fixed micro
    because best day $1,185.76 < 50%% of the $3,000 target — but binding once
    you scale contracts);
  * allow any contract count other than a hardcoded 1 or 2.

This simulator fixes all four and answers the actual question:
  "Keeping the champion's trade stream UNCHANGED (no signal re-tuning), how
   much income per funded 50K account per year does buffer-based contract
   scaling add, and at what blow-risk?"

MECHANICS
---------
* Session clock: the calendar of RTH sessions (>=1 bar in the 09:30-09:45 OR
  window of MNQ_full_1min.csv), zero P&L on no-trade sessions.  Cached to
  _sessions_rth.csv after the first (slow) build.
* Moving-block bootstrap over SESSIONS (default block=21 ~ one month),
  preserving losing streaks AND trade density.  The SAME resampled index
  matrix is shared by every policy -> paired comparison: differences between
  policies are policy effects, not sampling noise.
* Sizing (no lookahead): contracts for session d are decided from the PRIOR
  end-of-day state:
      headroom  = equity - dd_floor          (dollars of room to the kill line)
      contracts = clip(floor(headroom / step), 1, maxc)
  step=2000/maxc=1 reproduces the static 1-micro plan exactly (headroom at a
  fresh account start = the $2,000 limit -> exactly 1 micro).
* DD floor (profit-since-start coordinates), per the CONFIRMED LucidFlex rule
  (Lucid support, 2026-07-01): the MLL trails the EOD balance at -$2,000 until
  the balance closes above start+$2,100, then locks at start+$100 forever:
      lock=True  (real LucidFlex)  : floor = min(+100, peak - limit)
      lock=False (strict trailing) : floor = peak - limit   (kept for reference)
  Death = EOD equity <= floor.  EOD-only, like the Lucid rule.  Withdrawals
  do NOT move the locked line.
* Funded stage models the REAL Lucid payout cycle (confirmed 2026-07-01):
  a session qualifies if that day's net >= $150; after 5 qualifying days the
  account may request  w = min(50% of profit, $2,000)  (min request $500).
  Policy: also retain headroom >= step*maxc after the payout (keep enough
  room to hold the target size).  Trader receives 90% of w (90/10 split).
  Cycle day-count resets after each payout; no cooldown.
  Terminal equity at horizon end is credited at 90% (it is extractable over
  subsequent cycles, modulo risk).
* Eval stage adds the 50% consistency rule: PASS requires equity >= target
  AND best single winning day <= 50% of current equity; if the target is hit
  but the ratio fails, the account keeps trading until it satisfies both
  (or dies / times out).  No payouts during eval.

Anchors (sanity checks against the old numbers):
  * static 1 micro, rules-free annual net median should land near the old
    "+$3,894/yr per micro" (same bootstrap, session clock instead of trades).
  * static 1 micro eval pass/blow should land near the old 90% / 9%
    (clock change moves timeouts, not the race outcome).

Usage (from Python/, with the 3.12 interpreter that has numpy/pandas):
  python _scaling_mc.py
  python _scaling_mc.py --paths 20000 --block 21 --seed 12345
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ANSWER_KEY = HERE.parent / "Manual Tester" / "orb_answer_key.csv"
SESSIONS_CACHE = HERE / "_sessions_rth.csv"
MASTER_CSV = HERE / "MNQ_full_1min.csv"

# 50K LucidFlex account (confirmed w/ Lucid support 2026-07-01)
LIMIT = 2_000.0        # max EOD trailing drawdown ($48,000 initial floor)
LOCK_FLOOR = 100.0     # floor locks at start+$100 once peak profit hits $2,100
TARGET = 3_000.0       # eval profit target
CONSISTENCY = 0.50     # eval only: best day <= 50% of profit at pass time
PAYOUT_DAY_MIN = 150.0     # a session only counts toward a payout cycle if net >= this
PAYOUT_DAYS_REQUIRED = 5   # qualifying days needed per payout cycle
PAYOUT_PCT = 0.50          # may request up to 50% of profit per payout
PAYOUT_CAP = 2_000.0       # max withdrawal per payout request
PAYOUT_MIN = 500.0         # min withdrawal per payout request
PAYOUT_SPLIT = 0.90        # trader keeps 90% of each payout


# ---------------------------------------------------------------- data

def build_sessions() -> pd.Series:
    """All RTH session dates (>=1 bar in the 09:30-09:45 OR window), cached."""
    if SESSIONS_CACHE.exists():
        s = pd.read_csv(SESSIONS_CACHE, parse_dates=["date"])
        return s["date"].dt.date
    from orb_strategy import load_csv  # slow import path only on first build
    df = load_csv(str(MASTER_CSV), tz="America/New_York")
    t = df.index
    mask = (t.hour == 9) & (t.minute >= 30) & (t.minute < 45)
    dates = pd.Series(sorted(set(t[mask].date)), name="date")
    pd.DataFrame({"date": pd.to_datetime(dates)}).to_csv(SESSIONS_CACHE, index=False)
    return dates


def session_pnl() -> tuple[np.ndarray, int]:
    """Per-SESSION champion P&L (1 micro, $), zeros on no-trade sessions.

    Trimmed to the answer key's own date range so the ATR/ADX warmup period
    (no trades possible) doesn't dilute trade density.
    Returns (pnl array, number of trade sessions).
    """
    ak = pd.read_csv(ANSWER_KEY)
    ak["date"] = pd.to_datetime(ak["date"]).dt.date
    nets = dict(zip(ak["date"], ak["net"]))
    lo, hi = ak["date"].min(), ak["date"].max()
    days = [d for d in build_sessions() if lo <= d <= hi]
    pnl = np.array([nets.get(d, 0.0) for d in days], dtype=float)
    n_hit = int((pnl != 0).sum())
    if n_hit != len(ak):
        raise RuntimeError(
            f"answer-key dates not fully matched to sessions: {n_hit} != {len(ak)}"
        )
    return pnl, n_hit


def block_indices(n_src: int, n_out: int, block: int, rng) -> np.ndarray:
    """Moving-block bootstrap indices (same scheme as orb_montecarlo.py)."""
    if block <= 1 or n_src <= block:
        return rng.integers(0, n_src, size=n_out)
    n_blocks = int(np.ceil(n_out / block))
    starts = rng.integers(0, n_src - block + 1, size=n_blocks)
    idx = (starts[:, None] + np.arange(block)[None, :]).ravel()
    return idx[:n_out]


def index_matrix(n_src: int, paths: int, horizon: int, block: int, rng) -> np.ndarray:
    """(paths, horizon) bootstrap index matrix — one shared draw per stage."""
    return np.stack([block_indices(n_src, horizon, block, rng)
                     for _ in range(paths)]).astype(np.int32)


# ---------------------------------------------------------------- policies

@dataclass(frozen=True)
class Policy:
    name: str
    step: float      # dollars of headroom per micro
    maxc: int        # contract cap


FUNDED_POLICIES = [
    Policy("static 1 (baseline)",        2000, 1),
    Policy("scale /2000 cap 2",          2000, 2),
    Policy("scale /2000 cap 3",          2000, 3),
    Policy("scale /2000 cap 4",          2000, 4),
    Policy("scale /2000 cap 5",          2000, 5),
    Policy("scale /1500 cap 3 (aggr)",   1500, 3),
    Policy("scale /1500 cap 5 (aggr)",   1500, 5),
    Policy("scale /2500 cap 3 (conserv)", 2500, 3),
    Policy("scale /2500 cap 5 (conserv)", 2500, 5),
    Policy("scale /3000 cap 4 (v.cons)", 3000, 4),
    Policy("scale /1000 cap 3 (reckless)", 1000, 3),
]

EVAL_POLICIES = [
    Policy("static 1 (current plan)", 2000, 1),
    Policy("scale /2000 cap 2",       2000, 2),
    Policy("scale /1500 cap 2",       1500, 2),
    Policy("static 2 (known bad)",       1, 2),  # step $1 => always at cap
]

EVAL_FEE = 98.0    # new 50K eval
RESET_FEE = 95.0   # reset a blown eval


# ---------------------------------------------------------------- simulators

def _floor(peak: np.ndarray, lock: bool) -> np.ndarray:
    return np.minimum(LOCK_FLOOR, peak - LIMIT) if lock else peak - LIMIT


def _payout(eq: np.ndarray, peak: np.ndarray, lock: bool, pol: Policy,
            qual: np.ndarray, active: np.ndarray) -> np.ndarray:
    """Lucid payout request: eligible after PAYOUT_DAYS_REQUIRED qualifying
    days; w = min(50% of profit, $2,000), retaining headroom >= step*maxc;
    only executed if w >= the $500 minimum.  Returns w (0 where no payout)."""
    w = np.minimum(PAYOUT_PCT * np.maximum(eq, 0.0), PAYOUT_CAP)
    w = np.minimum(w, (eq - _floor(peak, lock)) - pol.step * pol.maxc)
    can = active & (qual >= PAYOUT_DAYS_REQUIRED) & (w >= PAYOUT_MIN)
    return np.where(can, w, 0.0)


def simulate_funded(path: np.ndarray, pol: Policy, lock: bool) -> dict:
    """One funded year (path = (P,H) per-1-micro session P&L).

    Returns per-path banked income (90% of payouts + 90% of terminal equity
    if alive), survival flags, payout count, and max contracts reached.
    """
    P, H = path.shape
    eq = np.zeros(P)
    peak = np.zeros(P)
    alive = np.ones(P, dtype=bool)
    income = np.zeros(P)
    max_con = np.zeros(P)
    qual = np.zeros(P)
    n_payouts = np.zeros(P)

    for d in range(H):
        # size for today from PRIOR EOD state (no lookahead)
        headroom = eq - _floor(peak, lock)
        con = np.clip(np.floor(headroom / pol.step), 1, pol.maxc)
        con = np.where(alive, con, 0.0)
        max_con = np.maximum(max_con, con)

        day = con * path[:, d]
        eq = eq + day
        peak = np.maximum(peak, eq)
        died = alive & (eq <= _floor(peak, lock))
        alive &= ~died

        qual = np.where(alive & (day >= PAYOUT_DAY_MIN), qual + 1, qual)
        w = _payout(eq, peak, lock, pol, qual, alive)
        income += PAYOUT_SPLIT * w
        eq -= w              # the locked MLL does NOT follow withdrawals
        n_payouts += (w > 0)
        qual = np.where(w > 0, 0, qual)

    income += np.where(alive, PAYOUT_SPLIT * np.maximum(eq, 0.0), 0.0)
    return {"income": income, "alive": alive, "max_con": max_con,
            "n_payouts": n_payouts}


def simulate_eval(path: np.ndarray, pol: Policy, lock: bool,
                  consistency: bool = True) -> dict:
    """Eval race on the session clock with optional 50% consistency rule."""
    P, H = path.shape
    eq = np.zeros(P)
    peak = np.zeros(P)
    best_day = np.zeros(P)
    alive = np.ones(P, dtype=bool)      # still racing
    passed = np.zeros(P, dtype=bool)
    blown = np.zeros(P, dtype=bool)
    pass_day = np.full(P, -1)
    delayed = np.zeros(P, dtype=bool)   # target hit but consistency blocked

    for d in range(H):
        headroom = eq - _floor(peak, lock)
        con = np.clip(np.floor(headroom / pol.step), 1, pol.maxc)
        day_pnl = np.where(alive, con * path[:, d], 0.0)

        eq = eq + day_pnl
        best_day = np.maximum(best_day, day_pnl)   # winning days only
        peak = np.maximum(peak, eq)

        die = alive & (eq <= _floor(peak, lock))
        blown |= die
        alive &= ~die

        hit = alive & (eq >= TARGET)
        if consistency:
            ok = hit & (best_day <= CONSISTENCY * eq)
            delayed |= hit & ~ok
        else:
            ok = hit
        pass_day = np.where(ok & (pass_day < 0), d + 1, pass_day)
        passed |= ok
        alive &= ~ok

    return {"passed": passed, "blown": blown, "timeout": alive,
            "pass_day": pass_day, "delayed": delayed}


def simulate_campaign(path: np.ndarray, size: int) -> dict:
    """Eval CAMPAIGN at a fixed micro size: blow -> pay reset, restart, repeat
    until pass.  Answers "how long and how many fees until I hold a funded
    account?"  Restart is next-session (real restarts take a day or two).
    Uses lock=True; the lock model barely matters pre-lock at these sizes.
    """
    P, H = path.shape
    eq = np.zeros(P)
    peak = np.zeros(P)
    best_day = np.zeros(P)
    fees = np.full(P, EVAL_FEE)
    racing = np.ones(P, dtype=bool)
    pass_day = np.full(P, -1)

    for d in range(H):
        day_pnl = np.where(racing, size * path[:, d], 0.0)
        eq = eq + day_pnl
        best_day = np.maximum(best_day, day_pnl)
        peak = np.maximum(peak, eq)

        die = racing & (eq <= _floor(peak, True))
        fees += np.where(die, RESET_FEE, 0.0)
        eq = np.where(die, 0.0, eq)          # reset and go again
        peak = np.where(die, 0.0, peak)
        best_day = np.where(die, 0.0, best_day)

        ok = racing & (eq >= TARGET) & (best_day <= CONSISTENCY * eq)
        pass_day = np.where(ok, d + 1, pass_day)
        racing &= ~ok

    return {"pass_day": pass_day, "fees": fees, "unfinished": racing}


def simulate_lifecycle(path: np.ndarray, eval_size: int, pol: Policy,
                       lock: bool) -> dict:
    """Full account-slot pipeline over the whole horizon:
    eval (fixed eval_size, consistency rule, blow->reset fee) -> funded
    (scaled sizing + Lucid payout cycles) -> funded death -> new eval -> ...

    income = 90% of payouts banked (+ 90% of terminal funded equity);
    fees = eval/reset fees paid.
    The bottom line for "returns": (income - fees) per year per account slot.
    """
    P, H = path.shape
    funded = np.zeros(P, dtype=bool)         # False = in eval
    eq = np.zeros(P)
    peak = np.zeros(P)
    best_day = np.zeros(P)                   # eval consistency tracker
    income = np.zeros(P)
    fees = np.full(P, EVAL_FEE)
    funded_days = np.zeros(P)
    passes = np.zeros(P)
    deaths = np.zeros(P)
    qual = np.zeros(P)                       # payout-cycle qualifying days
    n_payouts = np.zeros(P)

    for d in range(H):
        headroom = eq - _floor(peak, lock)
        con = np.where(funded,
                       np.clip(np.floor(headroom / pol.step), 1, pol.maxc),
                       float(eval_size))
        day_pnl = con * path[:, d]
        eq = eq + day_pnl
        peak = np.maximum(peak, eq)
        funded_days += funded

        die = eq <= _floor(peak, lock)
        # funded death -> buy a fresh eval; eval death -> pay reset
        fees += np.where(die & funded, EVAL_FEE, 0.0)
        fees += np.where(die & ~funded, RESET_FEE, 0.0)
        deaths += (die & funded)
        funded &= ~die
        eq = np.where(die, 0.0, eq)
        peak = np.where(die, 0.0, peak)
        best_day = np.where(die, 0.0, best_day)
        qual = np.where(die, 0.0, qual)

        # eval progress
        best_day = np.where(~funded, np.maximum(best_day, day_pnl), best_day)
        ok = ~funded & (eq >= TARGET) & (best_day <= CONSISTENCY * eq)
        passes += ok
        funded |= ok
        eq = np.where(ok, 0.0, eq)           # funded account starts fresh
        peak = np.where(ok, 0.0, peak)
        qual = np.where(ok, 0.0, qual)

        # funded payout cycle (Lucid rules)
        qual = np.where(funded & ~ok & (day_pnl >= PAYOUT_DAY_MIN),
                        qual + 1, qual)
        w = _payout(eq, peak, lock, pol, qual, funded)
        income += PAYOUT_SPLIT * w
        eq -= w              # the locked MLL does NOT follow withdrawals
        n_payouts += (w > 0)
        qual = np.where(w > 0, 0, qual)

    # unswept funded balance at horizon end is extractable over later cycles
    income += np.where(funded, PAYOUT_SPLIT * np.maximum(eq, 0.0), 0.0)
    return {"income": income, "fees": fees, "funded_days": funded_days,
            "passes": passes, "deaths": deaths, "n_payouts": n_payouts}


# ---------------------------------------------------------------- reporting

S2CAL = 365.25 / 252.0   # sessions -> calendar days


def pct(a, q):
    return float(np.percentile(a, q))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=10_000)
    ap.add_argument("--block", type=int, default=21)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--horizon", type=int, default=252)      # funded year, sessions
    ap.add_argument("--eval-horizon", type=int, default=504)  # ~2 calendar years
    ap.add_argument("--life-horizon", type=int, default=1260)  # ~5 calendar years
    a = ap.parse_args()

    pnl, n_trades = session_pnl()
    n = len(pnl)
    print(f"sessions={n}  trade-sessions={n_trades} ({n_trades/n:.1%} density)  "
          f"net=${pnl.sum():,.2f}  block={a.block}  paths={a.paths:,}  seed={a.seed}")

    # one long shared draw; stages slice their horizon from it (paired paths)
    rng = np.random.default_rng(a.seed)
    idx_life = index_matrix(n, a.paths, a.life_horizon, a.block, rng)
    path_life = pnl[idx_life]
    path_funded = path_life[:, :a.horizon]
    path_eval = path_life[:, :a.eval_horizon]

    # anchor: rules-free static 1-micro annual net (compare to old ~$3,894)
    nets = path_funded.sum(axis=1)
    print(f"\nANCHOR rules-free 1-micro year: median ${pct(nets,50):,.0f}  "
          f"[5th ${pct(nets,5):,.0f} / 95th ${pct(nets,95):,.0f}]")

    for lock in (True, False):
        tag = ("lock at start+$100 (real LucidFlex)" if lock
               else "strict always-trailing")
        print(f"\n=== FUNDED YEAR -- 50K, {tag}, income post-90/10 split ===")
        print(f"{'policy':<26}{'P(dead)':>8}{'med inc':>10}{'mean':>10}"
              f"{'5th':>9}{'95th':>10}{'med maxC':>9}{'med pay':>8}")
        for pol in FUNDED_POLICIES:
            r = simulate_funded(path_funded, pol, lock)
            inc = r["income"]
            print(f"{pol.name:<26}{1 - r['alive'].mean():>8.1%}"
                  f"{pct(inc,50):>10,.0f}{inc.mean():>10,.0f}"
                  f"{pct(inc,5):>9,.0f}{pct(inc,95):>10,.0f}"
                  f"{np.median(r['max_con']):>9.0f}"
                  f"{np.median(r['n_payouts']):>8.0f}")

    for lock in (True, False):
        tag = "lock-at-start" if lock else "strict trailing"
        print(f"\n=== EVAL RACE -- 50K ($3,000 / $2,000), {tag}, "
              f"consistency 50% on ===")
        print(f"{'policy':<26}{'PASS':>7}{'BLOW':>7}{'TIMEOUT':>8}"
              f"{'med cal-days':>13}{'<=252s':>8}{'delayed':>8}")
        for pol in EVAL_POLICIES:
            r = simulate_eval(path_eval, pol, lock)
            pd_ = r["pass_day"][r["pass_day"] > 0]
            med = np.median(pd_) * S2CAL if pd_.size else float("nan")
            within = (r["pass_day"] > 0) & (r["pass_day"] <= 252)
            print(f"{pol.name:<26}{r['passed'].mean():>7.1%}{r['blown'].mean():>7.1%}"
                  f"{r['timeout'].mean():>8.1%}{med:>13.0f}"
                  f"{within.mean():>8.1%}{r['delayed'].mean():>8.1%}")

    # eval campaign: repeat-until-pass at a fixed size
    print(f"\n=== EVAL CAMPAIGN -- blow => ${RESET_FEE:.0f} reset, repeat until "
          f"pass (lock-at-start, consistency on) ===")
    print(f"{'size':<10}{'med cal-days':>13}{'mean':>8}{'90th':>8}"
          f"{'mean fees':>10}{'pass<=1yr':>10}{'unfinished':>11}")
    for size in (1, 2, 3, 4):
        r = simulate_campaign(path_life, size)
        d_ = r["pass_day"][r["pass_day"] > 0].astype(float) * S2CAL
        w1 = ((r["pass_day"] > 0) & (r["pass_day"] <= 252)).mean()
        print(f"{size} micro{'s' if size>1 else ' ':<3}{np.median(d_):>13.0f}"
              f"{d_.mean():>8.0f}{np.percentile(d_,90):>8.0f}"
              f"{r['fees'].mean():>10,.0f}{w1:>10.1%}"
              f"{r['unfinished'].mean():>11.1%}")

    # full lifecycle: eval -> funded -> death -> new eval, over ~5 years
    years = a.life_horizon / 252.0
    combos = [
        ("A: eval@1 + funded static1 (CURRENT)", 1, FUNDED_POLICIES[0]),
        ("B: eval@2 + funded static1",           2, FUNDED_POLICIES[0]),
        ("C: eval@2 + funded scale cap3",        2, FUNDED_POLICIES[2]),
        ("D: eval@2 + funded scale cap5",        2, FUNDED_POLICIES[4]),
        ("E: eval@3 + funded scale cap3",        3, FUNDED_POLICIES[2]),
        ("F: eval@1 + funded scale cap3",        1, FUNDED_POLICIES[2]),
    ]
    for lock in (True, False):
        tag = ("lock at start+$100 (real LucidFlex)" if lock
               else "strict always-trailing")
        print(f"\n=== LIFECYCLE per account slot, {years:.0f}y horizon, {tag}, "
              f"income post-90/10 split ===")
        print(f"{'combo':<38}{'net $/yr':>9}{'med $/yr':>9}{'5th':>7}"
              f"{'fees/yr':>8}{'%funded':>8}{'pay/yr':>7}{'deaths':>7}")
        for name, esize, pol in combos:
            r = simulate_lifecycle(path_life, esize, pol, lock)
            net = (r["income"] - r["fees"]) / years
            print(f"{name:<38}{net.mean():>9,.0f}{pct(net,50):>9,.0f}"
                  f"{pct(net,5):>7,.0f}{r['fees'].mean()/years:>8,.0f}"
                  f"{r['funded_days'].mean()/a.life_horizon:>8.1%}"
                  f"{r['n_payouts'].mean()/years:>7.2f}"
                  f"{r['deaths'].mean()/years:>7.2f}")

    # block-size sensitivity on the headline funded policies
    print("\n=== SENSITIVITY -- block size, lock-at-start, funded year ===")
    for blk in (10, 21, 42):
        rng2 = np.random.default_rng(a.seed + blk)
        pf = pnl[index_matrix(n, a.paths, a.horizon, blk, rng2)]
        row = [f"block={blk:>2}"]
        for pol in (FUNDED_POLICIES[0], FUNDED_POLICIES[2], FUNDED_POLICIES[4]):
            r = simulate_funded(pf, pol, lock=True)
            row.append(f"{pol.maxc}c: med ${pct(r['income'],50):,.0f} "
                       f"dead {1 - r['alive'].mean():.1%}")
        print("  ".join(row))


if __name__ == "__main__":
    main()
