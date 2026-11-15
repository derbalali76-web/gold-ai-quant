"""Independent crypto scalping engine on 1-minute data (BTC, ETH, SOL) — research and validation.

PRE-REGISTERED 2026-11-15, BEFORE any result was seen. Nothing below may be tuned after looking at results; a new
idea becomes a new, separately declared round.

Data      Binance spot 1-minute klines (real volume + taker-buy volume) 2021 -> now. 3-min and 5-min bars are built
          from them; the reference trend uses only CLOSED 15-min and 1-hour bars (no look-ahead).
Side      long only (spot users).
Trend     allowed only when the last closed 1-hour close > its EMA50 AND the last closed 15-min EMA20 > EMA50.
Setups    an order is planned at a signal bar's close and becomes active on the NEXT 1-minute bar:
  BREAKOUT_RETEST    5-min close above the highest high of the previous 12 x 5-min bars (1 h) -> buy limit AT that
                     broken high (the retest), valid 30 min
  LEVEL_BOUNCE       5-min close within 0.30 % above the lowest low of the previous 48 x 5-min bars (4 h, excluding
                     the last 3) -> buy limit 0.05 % above that support, valid 30 min
  MOMENTUM_CONT      three rising 3-min closes, +0.30 % or more in total, taker-buy share of the three > 55 % and
                     volume above its 1-day average -> buy limit at the middle of the last 3-min bar, valid 9 min
Fills     a limit buy fills only if a later 1-min LOW trades THROUGH it (0.01 % below), never on a touch; the target is
          a limit sell that fills only if a HIGH trades 0.01 % through it. Unfilled orders are counted separately.
Exit      target +0.65 % gross from entry; stop variants (pre-registered):
  FIXED   -0.50 %
  ATR     1.5 x ATR(14) of 5-min bars, clipped to [0.25 %, 1.00 %]
  TRAIL   starts as ATR; after +0.35 % the stop moves to entry + costs (break-even); then trails 1 x ATR below the
          highest high
          max hold 120 min (exit at the close). If one bar could hit both stop and target, the STOP counts; a stop
          in the fill bar counts; a target in the fill bar does not.
Costs     configurable: fees (default 0.15 % round trip, Binance with BNB) + spread + slippage on stop/timeout exits.
Judging   rules have no fitted parameters, so every year is out of sample; the last 20 % of time is the final
          holdout. 27 combinations (3 setups x 3 stops x 3 coins) -> 99.8 % confidence (Bonferroni-style).
          A combination qualifies only if ALL hold:
            >= 200 filled trades; average net CI above zero; every calendar year positive (>= 20 trades); holdout
            positive (>= 50 trades); beats the baseline (same exits, entries at evenly spaced trend-allowed minutes,
            market orders) with a CI above zero.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

VERSION = "scalp1m-1"
SETUPS = ("BREAKOUT_RETEST", "LEVEL_BOUNCE", "MOMENTUM_CONT")
STOPS = ("FIXED", "ATR", "TRAIL")
TARGET = 0.0065
FIXED_STOP = 0.0050
ATR_MULT, ATR_MIN, ATR_MAX = 1.5, 0.0025, 0.0100
TRAIL_ARM, TRAIL_MULT = 0.0035, 1.0
MAX_HOLD = 120
THROUGH = 0.0001
CI_LEVEL = 99.8
HOLDOUT_FRAC = 0.2


@dataclass
class Costs:
    fees: float = 0.0015  # round trip, both sides
    spread: float = 0.0001
    slippage: float = 0.0002  # market exits only (stop / timeout)

    @property
    def base(self):
        return self.fees + self.spread


ASSET_SPREAD = {"BTC": 0.0001, "ETH": 0.0001, "SOL": 0.0002}


@dataclass
class Report:
    asset: str
    setup: str
    stop: str
    version: str = VERSION
    costs: dict = field(default_factory=dict)
    period: str = ""
    orders: int = 0
    filled: int = 0
    unfilled: int = 0
    targets: int = 0
    stops: int = 0
    timeouts: int = 0
    win_rate: Optional[float] = None
    avg_net_pct: Optional[float] = None
    avg_net_ci: Optional[list] = None
    total_net_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    trades_per_week: Optional[float] = None
    years: dict = field(default_factory=dict)
    holdout_trades: int = 0
    holdout_avg_pct: Optional[float] = None
    baseline_avg_pct: Optional[float] = None
    baseline_holdout_avg_pct: Optional[float] = None
    edge_ci: Optional[list] = None
    gross_avg_pct: Optional[float] = None
    qualified: bool = False
    reason: str = ""
    checks: dict = field(default_factory=dict)


# ---------------------------------------------------------------- bars and causal context
def resample(m1: pd.DataFrame, minutes: int) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "taker_buy_volume" in m1.columns:
        agg["taker_buy_volume"] = "sum"
    return m1.resample(f"{minutes}min", label="left", closed="left").agg(agg).dropna(subset=["close"])


def _closed_on_1m(m1: pd.DataFrame, htf: pd.DataFrame, minutes: int, values: np.ndarray) -> np.ndarray:
    """For each 1-min bar (index = open time), the value of the last HIGHER-TF bar that had CLOSED by that bar's open."""
    avail = (htf.index + pd.Timedelta(minutes=minutes)).asi8
    pos = np.searchsorted(avail, m1.index.asi8, side="right") - 1
    out = np.full(len(m1), np.nan)
    ok = pos >= 0
    out[ok] = values[pos[ok]]
    return out


def _atr(df: pd.DataFrame, n=14) -> np.ndarray:
    h, lo, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    return (tr.rolling(n).mean() / c).to_numpy(float)


def context(m1: pd.DataFrame) -> dict:
    m5, m15, h1 = resample(m1, 5), resample(m1, 15), resample(m1, 60)
    t15 = (m15["close"].ewm(span=20, adjust=False).mean() > m15["close"].ewm(span=50, adjust=False).mean())
    t1h = h1["close"] > h1["close"].ewm(span=50, adjust=False).mean()
    trend = (_closed_on_1m(m1, m15, 15, t15.to_numpy(float)) == 1) & (_closed_on_1m(m1, h1, 60, t1h.to_numpy(float)) == 1)
    atr5 = _closed_on_1m(m1, m5, 5, _atr(m5))
    return {"trend": trend, "atr5": atr5, "m5": m5}


# ---------------------------------------------------------------- setups -> planned orders (signal time, price, ttl)
def plan(m1: pd.DataFrame, setup: str, ctx: dict) -> list[tuple[int, float, int]]:
    """Orders as (first active 1-min position, limit price, minutes valid). Uses only bars closed before activation."""
    if setup == "MOMENTUM_CONT":
        tf, bars = 3, resample(m1, 3)
        c = bars["close"]
        up3 = (c > c.shift(1)) & (c.shift(1) > c.shift(2)) & (c.shift(2) > c.shift(3))
        move = c / c.shift(3) - 1
        tb = bars["taker_buy_volume"] if "taker_buy_volume" in bars.columns else bars["volume"] * 0.5
        share = tb.rolling(3).sum() / bars["volume"].rolling(3).sum().replace(0, np.nan)
        vavg = bars["volume"].rolling(480, min_periods=200).mean()  # 1 day of 3-min bars
        sig = up3 & (move >= 0.003) & (share > 0.55) & (bars["volume"].rolling(3).mean() > vavg)
        price = ((bars["high"] + bars["low"]) / 2).to_numpy(float)
        ttl = 9
    else:
        tf, bars = 5, ctx["m5"]
        c = bars["close"]
        if setup == "BREAKOUT_RETEST":
            lvl = bars["high"].rolling(12).max().shift(1)
            sig = c > lvl
            price = lvl.to_numpy(float)
        elif setup == "LEVEL_BOUNCE":
            sup = bars["low"].shift(3).rolling(45).min()
            sig = (c >= sup) & (c <= sup * 1.003)
            price = (sup * 1.0005).to_numpy(float)
        else:
            raise ValueError(setup)
        ttl = 30
    sig = sig.fillna(False).to_numpy(bool)
    avail = (bars.index + pd.Timedelta(minutes=tf)).asi8
    pos = np.searchsorted(m1.index.asi8, avail[sig], side="left")
    pr = price[sig]
    ok = (pos < len(m1)) & np.isfinite(pr)
    pos, pr = pos[ok], pr[ok]
    tr = ctx["trend"]
    keep = tr[pos]  # trend known at activation (closed higher-TF bars only)
    return [(int(p), float(x), ttl) for p, x in zip(pos[keep], pr[keep])]


# ---------------------------------------------------------------- execution simulator (1-minute, conservative)
def _exit(o, h, lo, c, j0, entry, stop_kind, atr, costs: Costs, fill_bar_low=None):
    n = len(c)
    tgt = entry * (1 + TARGET)
    if stop_kind == "FIXED":
        sl = entry * (1 - FIXED_STOP)
    else:
        sl = entry * (1 - float(np.clip(ATR_MULT * atr, ATR_MIN, ATR_MAX)))
    armed, hh = False, entry
    if fill_bar_low is not None and fill_bar_low <= sl:  # stop inside the fill bar counts
        return (sl * (1 - costs.slippage) - entry) / entry - costs.base, "STOP", j0, (sl - entry) / entry
    end = min(n - 1, j0 + MAX_HOLD)
    for j in range(j0 + 1, end + 1):
        if lo[j] <= sl:
            px = min(o[j], sl)  # gap through the stop exits at the open
            px *= (1 - costs.slippage)
            return (px - entry) / entry - costs.base, "STOP", j, (px - entry) / entry
        if h[j] >= tgt * (1 + THROUGH):
            return TARGET - costs.base, "TARGET", j, TARGET
        if stop_kind == "TRAIL":
            hh = max(hh, h[j])
            if not armed and hh >= entry * (1 + TRAIL_ARM):
                armed = True
            if armed:
                sl = max(sl, entry * (1 + costs.base), hh * (1 - TRAIL_MULT * atr))
    px = c[end] * (1 - costs.slippage)
    return (px - entry) / entry - costs.base, "TIMEOUT", end, (px - entry) / entry


def simulate(m1: pd.DataFrame, orders, stop_kind: str, atr5: np.ndarray, costs: Costs):
    o, h, lo, c = (m1[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n, out, free, unfilled, placed = len(c), [], -1, 0, 0
    for p, price, ttl in orders:
        if p <= free or p >= n - 1 or not np.isfinite(atr5[p]):
            continue
        placed += 1
        lim = price * (1 - THROUGH)
        fill = None
        for j in range(p, min(n - 1, p + ttl)):
            if o[j] <= lim:  # opened below the limit: filled at the open (better price)
                fill, ep = j, o[j]
                break
            if lo[j] <= lim:
                fill, ep = j, price
                break
        if fill is None:
            unfilled += 1
            free = min(n - 1, p + ttl - 1)
            continue
        r, how, k, gross = _exit(o, h, lo, c, fill, ep, stop_kind, atr5[p], costs, fill_bar_low=lo[fill])
        out.append((fill, r, how, gross))
        free = k
    return out, placed, unfilled


def _market_baseline(m1, positions, stop_kind, atr5, costs):
    o, h, lo, c = (m1[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    out, free = [], -1
    for p in positions:
        if p <= free or p >= len(c) - 1 or not np.isfinite(atr5[p]):
            continue
        ep = o[p] * (1 + costs.slippage)  # market buy at the open of the bar
        r, how, k, g = _exit(o, h, lo, c, p, ep, stop_kind, atr5[p], costs, fill_bar_low=lo[p])
        out.append((p, r, how, g))
        free = k
    return out


def _ci(x, level=CI_LEVEL, n=2000, seed=7):
    if len(x) < 10:
        return None
    rng = np.random.default_rng(seed)
    m = [float(np.mean(rng.choice(x, len(x)))) for _ in range(n)]
    a = (100 - level) / 2
    return [round(float(np.percentile(m, a)) * 100, 4), round(float(np.percentile(m, 100 - a)) * 100, 4)]


def backtest(m1: pd.DataFrame, asset: str, setup: str, stop_kind: str, costs: Costs, ctx: Optional[dict] = None,
             orders=None, ci_level: Optional[float] = None) -> Report:
    lvl = ci_level or CI_LEVEL
    m1 = m1.dropna(subset=["open", "high", "low", "close"])
    rep = Report(asset=asset, setup=setup, stop=stop_kind, costs=asdict(costs))
    if len(m1) < 60 * 24 * 60:
        rep.reason = "insufficient data"
        return rep
    ctx = ctx or context(m1)
    orders = orders if orders is not None else plan(m1, setup, ctx)
    trades, placed, unfilled = simulate(m1, orders, stop_kind, ctx["atr5"], costs)
    rep.period = f"{m1.index[0].date()} -> {m1.index[-1].date()}"
    rep.orders, rep.unfilled, rep.filled = placed, unfilled, len(trades)
    if not trades:
        rep.reason = "no filled trade"
        return rep
    r = np.array([t[1] for t in trades])
    rep.targets = sum(t[2] == "TARGET" for t in trades)
    rep.stops = sum(t[2] == "STOP" for t in trades)
    rep.timeouts = sum(t[2] == "TIMEOUT" for t in trades)
    rep.win_rate = round(float((r > 0).mean()), 4)
    rep.avg_net_pct = round(float(r.mean()) * 100, 4)
    rep.gross_avg_pct = round(float(np.mean([t[3] for t in trades])) * 100, 4)
    rep.avg_net_ci = _ci(r, level=lvl)
    eq = np.cumsum(r)
    rep.total_net_pct = round(float(eq[-1]) * 100, 2)
    rep.max_drawdown_pct = round(float(np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq])) * 100, 2)
    rep.trades_per_week = round(len(r) / max((m1.index[-1] - m1.index[0]).days / 7, 1), 2)
    t_idx = m1.index[[t[0] for t in trades]]
    for y in sorted(set(t_idx.year)):
        ry = r[t_idx.year == y]
        rep.years[str(y)] = {"trades": int(len(ry)), "avg_net_pct": round(float(ry.mean()) * 100, 4)}
    cut = m1.index[int(len(m1) * (1 - HOLDOUT_FRAC))]
    ho = r[t_idx >= cut]
    rep.holdout_trades = int(len(ho))
    rep.holdout_avg_pct = round(float(ho.mean()) * 100, 4) if len(ho) else None
    pool = np.flatnonzero(ctx["trend"])
    if len(pool):
        bpos = pool[np.linspace(0, len(pool) - 1, min(len(pool), len(r) * 3)).astype(int)]
        base = _market_baseline(m1, bpos, stop_kind, ctx["atr5"], costs)
        b = np.array([t[1] for t in base])
        if len(b):
            rep.baseline_avg_pct = round(float(b.mean()) * 100, 4)
            bho = b[m1.index[[t[0] for t in base]] >= cut]
            rep.baseline_holdout_avg_pct = round(float(bho.mean()) * 100, 4) if len(bho) else None
            rng = np.random.default_rng(11)
            d = [float(np.mean(rng.choice(r, len(r))) - np.mean(rng.choice(b, len(b)))) for _ in range(2000)]
            a = (100 - lvl) / 2
            rep.edge_ci = [round(float(np.percentile(d, a)) * 100, 4), round(float(np.percentile(d, 100 - a)) * 100, 4)]
    yrs = [v for v in rep.years.values() if v["trades"] >= 20]
    ck = {
        "at least 200 filled trades": rep.filled >= 200,
        "average net CI above zero": bool(rep.avg_net_ci and rep.avg_net_ci[0] > 0),
        "every year positive": bool(yrs) and all(v["avg_net_pct"] > 0 for v in yrs),
        "final holdout positive": rep.holdout_trades >= 50 and (rep.holdout_avg_pct or 0) > 0,
        "beats baseline (CI)": bool(rep.edge_ci and rep.edge_ci[0] > 0),
    }
    rep.checks = ck
    rep.qualified = all(ck.values())
    rep.reason = "qualified" if rep.qualified else "failed: " + "; ".join(k for k, v in ck.items() if not v)
    return rep


def run_asset(m1: pd.DataFrame, asset: str, costs: Optional[Costs] = None) -> list[dict]:
    costs = costs or Costs(spread=ASSET_SPREAD.get(asset, 0.0002))
    ctx = context(m1)
    out = []
    for s in SETUPS:
        orders = plan(m1, s, ctx)
        for k in STOPS:
            out.append(asdict(backtest(m1, asset, s, k, costs, ctx, orders)))
    return out


# ---------------------------------------------------------------- ROUND 4 (pre-registered 2026-11-15, before results)
ROUND4_VERSION = "scalp1m-r4"
ROUND4_CI = 99.9  # 45 combinations (5 setups x 3 stops x 3 coins)
ROUND4_SETUPS = ("BREAKOUT_RETEST+ACT", "LEVEL_BOUNCE+ACT", "MOMENTUM_CONT+ACT", "DIP_FADE", "DIP_FADE+ACT")
ROUND4_DOC = """Round 4 (pre-registered before any result):
  +ACT      the round-1 setup, kept only when the market-activity forecast is HIGH: probability >= usual + 10 points.
            The forecast is the OUT-OF-SAMPLE walk-forward prediction (expanding window by calendar year, 2022 ->),
            made hourly from closed 15-min bars, so 2021 is not traded in round 4.
  DIP_FADE  1-hour trend up (last closed 1-h close > EMA50) and the last three 5-min bars fell 0.50 % or more in total
            -> buy limit 0.20 % below the last close, valid 15 min (provide liquidity into the drop).
  Exits, fills, costs, baseline and qualification rules: identical to round 1, at 99.9 % confidence."""


def activity_gate(m1: pd.DataFrame) -> tuple[np.ndarray, dict]:
    from . import activity as ACT
    m15 = resample(m1, 15)
    rep = ACT.evaluate(m15, return_preds=True)
    pr = rep.pop("preds", None)
    gate = np.zeros(len(m1), bool)
    if pr is not None and len(pr):
        hi = ((pr["p"] >= pr["usual"] + 0.10).to_numpy(float))
        gate = _closed_on_1m(m1, pr, 15, hi) == 1
    return gate, {k: rep.get(k) for k in ("skill", "skill_ci99", "holdout_skill", "qualified", "reason")}


def plan_r4(m1: pd.DataFrame, setup: str, ctx: dict, gate: np.ndarray) -> list[tuple[int, float, int]]:
    base, act = setup.split("+")[0], setup.endswith("+ACT")
    if base == "DIP_FADE":
        m5, h1 = ctx["m5"], resample(m1, 60)
        up = (h1["close"] > h1["close"].ewm(span=50, adjust=False).mean()).to_numpy(float)
        t1h = _closed_on_1m(m1, h1, 60, up) == 1
        c = m5["close"]
        sig = ((c / c.shift(3) - 1) <= -0.005).fillna(False).to_numpy(bool)
        price = (c * (1 - 0.002)).to_numpy(float)
        avail = (m5.index + pd.Timedelta(minutes=5)).asi8
        pos = np.searchsorted(m1.index.asi8, avail[sig], side="left")
        pr = price[sig]
        ok = pos < len(m1)
        pos, pr = pos[ok], pr[ok]
        keep = t1h[pos]
        orders = [(int(p), float(x), 15) for p, x in zip(pos[keep], pr[keep])]
    else:
        orders = plan(m1, base, ctx)
    if act:
        orders = [o for o in orders if gate[o[0]]]
    return orders


def run_round4(m1: pd.DataFrame, asset: str, costs: Optional[Costs] = None) -> dict:
    costs = costs or Costs(spread=ASSET_SPREAD.get(asset, 0.0002))
    gate, act_rep = activity_gate(m1)
    first = np.flatnonzero(gate)
    start = m1.index[0] if not len(first) else pd.Timestamp(f"{m1.index[first[0]].year}-01-01", tz="UTC")
    start = max(start, pd.Timestamp("2022-01-01", tz="UTC"))
    keep = m1.index >= start
    m1, gate = m1[keep], gate[keep]
    ctx = context(m1)
    out = []
    for s in ROUND4_SETUPS:
        orders = plan_r4(m1, s, ctx, gate)
        for k in STOPS:
            r = backtest(m1, asset, s, k, costs, ctx, orders, ci_level=ROUND4_CI)
            r.version = ROUND4_VERSION
            out.append(asdict(r))
    return {"activity_forecast": act_rep, "gate_share": round(float(gate.mean()), 4), "results": out}


def fee_sensitivity(m1: pd.DataFrame, asset: str, fees=(0.0010, 0.0005)) -> list[dict]:
    """Information only (never used to qualify): the same tests at lower fee tiers."""
    ctx, out = context(m1), []
    for f in fees:
        c = Costs(fees=f, spread=ASSET_SPREAD.get(asset, 0.0002))
        for s in SETUPS:
            orders = plan(m1, s, ctx)
            for k in STOPS:
                r = backtest(m1, asset, s, k, c, ctx, orders)
                out.append({"fees": f, "setup": s, "stop": k, "filled": r.filled, "avg_net_pct": r.avg_net_pct,
                            "holdout_avg_pct": r.holdout_avg_pct, "baseline_avg_pct": r.baseline_avg_pct})
    return out
