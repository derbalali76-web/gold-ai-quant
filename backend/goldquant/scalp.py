"""Scalping lab: pre-registered fast rules on 15-minute bars, judged after costs, on data the rules never saw.

The user's target: +0.65 % gross per trade (≈ +0.5 % net after Binance spot fees paid in BNB, 0.075 % per side).
Rules are fixed BEFORE testing and few on purpose (every extra variant raises the chance of a lucky result):

  BREAKOUT_LONG   15-min close above the highest high of the previous 24 h      -> buy at that close
  BREAKOUT_SHORT  15-min close below the lowest low of the previous 24 h        -> sell at that close (perps / CFD)
  PULLBACK_LONG   uptrend (EMA50 > EMA200) and a close at least 1 ATR below EMA20 -> buy at that close

Exits: target +0.65 % from entry, stop -0.40 % or -0.65 % (two pre-registered variants), or the close after 4 h.
If one bar touches both the target and the stop, the STOP is counted. One open trade per rule at a time.
Every result is net of the round-trip cost given (fees + spread + slippage).
Baseline: the same exits entered at evenly spaced times (same number of trades) — does the rule's timing add value?
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

RULES = ("BREAKOUT_LONG", "BREAKOUT_SHORT", "PULLBACK_LONG")
# Round 2 (pre-registered 2026-11-15, BEFORE looking at any result): information beyond price.
# Crypto (real volume, taker-buy share, perpetual funding) — long only (spot users):
CRYPTO_RULES2 = ("FLOW_BREAKOUT_LONG", "TAKER_SURGE_LONG", "FUNDING_FADE_LONG", "CAPITULATION_REVERSAL_LONG")
# Gold (session opens, when the big intraday moves start):
GOLD_RULES2 = ("LONDON_OPEN_LONG", "LONDON_OPEN_SHORT", "NY_OPEN_LONG", "NY_OPEN_SHORT")
# Round 3 (pre-registered 2026-11-15, from published studies, BEFORE looking at any result):
#   INTRADAY_MOMENTUM_LONG  Shen, Urquhart & Wang (Financial Review 2022): the day's early return predicts its
#                           last part -> at 22:00 UTC buy if the day so far (00:00 -> 22:00 UTC) is up
#   LATE_HOUR_LONG          Quantpedia (Gemini data 2015-2022): 22:00-23:00 UTC were the strongest hours
#                           -> buy at 21:00 UTC every day
CRYPTO_RULES3 = ("INTRADAY_MOMENTUM_LONG", "LATE_HOUR_LONG")
CI_ROUND2 = 99.0  # more rules tested -> stricter confidence (Bonferroni-style) before anything can qualify
TARGET = 0.0065
STOPS = (0.0040, 0.0065)
MAX_BARS = 16  # 4 hours of 15-min bars
LOOKBACK = 96  # 24 hours of 15-min bars
HOLDOUT_FRAC = 0.2


@dataclass
class ScalpReport:
    rule: str
    stop: float
    cost: float
    period: str = ""
    trades: int = 0
    targets: int = 0
    stops: int = 0
    timeouts: int = 0
    win_rate: Optional[float] = None
    avg_net_pct: Optional[float] = None
    avg_net_ci95: Optional[list] = None
    halves_pct: Optional[list] = None
    holdout_trades: int = 0
    holdout_avg_pct: Optional[float] = None
    total_net_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    trades_per_week: Optional[float] = None
    baseline_avg_pct: Optional[float] = None
    edge_ci95: Optional[list] = None
    qualified: bool = False
    reason: str = ""
    checks: dict = field(default_factory=dict)


def signals(df: pd.DataFrame, rule: str) -> np.ndarray:
    c, h, l = df["close"].to_numpy(float), df["high"], df["low"]
    if rule == "BREAKOUT_LONG":
        prev_hi = h.rolling(LOOKBACK).max().shift(1).to_numpy(float)
        return c > prev_hi
    if rule == "BREAKOUT_SHORT":
        prev_lo = l.rolling(LOOKBACK).min().shift(1).to_numpy(float)
        return c < prev_lo
    if rule == "PULLBACK_LONG":
        cs = df["close"]
        e20, e50, e200 = (cs.ewm(span=n, adjust=False).mean() for n in (20, 50, 200))
        tr = pd.concat([h - l, (h - cs.shift()).abs(), (l - cs.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        return ((e50 > e200) & (cs <= e20 - atr)).to_numpy() & np.isfinite(atr.to_numpy())
    return _signals2(df, rule)


def _vol_z(df):
    lv = np.log(df["volume"].astype(float).clip(lower=1e-12))
    return ((lv - lv.rolling(96).mean()) / lv.rolling(96).std()).to_numpy()


def _signals2(df: pd.DataFrame, rule: str) -> np.ndarray:
    c, o = df["close"], df["open"]
    if rule in CRYPTO_RULES2:
        share = (df["taker_buy_volume"] / df["volume"].replace(0, np.nan)).to_numpy()
        vz = _vol_z(df)
        if rule == "FLOW_BREAKOUT_LONG":  # breakout backed by a real volume burst bought aggressively
            prev_hi = df["high"].rolling(LOOKBACK).max().shift(1).to_numpy(float)
            return (c.to_numpy() > prev_hi) & (vz > 2.0) & (share > 0.6)
        if rule == "TAKER_SURGE_LONG":  # an hour of aggressive buying on high volume, above the short trend
            s4 = pd.Series(share).rolling(4).mean().to_numpy()
            e50 = c.ewm(span=50, adjust=False).mean().to_numpy()
            return (s4 > 0.62) & (vz > 1.5) & (c.to_numpy() > e50)
        if rule == "FUNDING_FADE_LONG":  # crowded shorts (negative funding) and price turns back up
            f = df["funding"].to_numpy(float) if "funding" in df.columns else np.full(len(df), np.nan)
            e20 = c.ewm(span=20, adjust=False).mean()
            cross = (c > e20) & (c.shift(1) <= e20.shift(1))
            return (f < -0.0003) & cross.to_numpy()
        if rule == "CAPITULATION_REVERSAL_LONG":  # sharp 1-hour drop on heavy volume, then a buying candle
            drop = (c / c.shift(4) - 1).to_numpy()
            return (pd.Series(drop).shift(1).to_numpy() < -0.025) & (pd.Series(vz).shift(1).to_numpy() > 2.0) & \
                (c > o).to_numpy()
    if rule in CRYPTO_RULES3:
        idx = df.index + pd.Timedelta(minutes=15)  # bar close time (index = bar open)
        mins = idx.hour * 60 + idx.minute
        if rule == "LATE_HOUR_LONG":
            return np.asarray(mins == 21 * 60)
        day = (df.index).floor("D")
        first_open = df["open"].groupby(day).transform("first").to_numpy(float)
        return np.asarray(mins == 22 * 60) & (c.to_numpy(float) > first_open)
    if rule in GOLD_RULES2:
        idx = df.index
        if rule.startswith("LONDON"):  # London open (08:00-10:00 London time) breaks the Asian range (00:00-07:00 UTC)
            local = idx.tz_convert("Europe/London")
            day = idx.floor("D")
            asia = (idx.hour < 7)
            hi = df["high"].where(asia).groupby(day).transform("max").to_numpy(float)
            lo = df["low"].where(asia).groupby(day).transform("min").to_numpy(float)
            window = ((local.hour >= 8) & (local.hour < 10))
        else:  # New York open (08:30-10:30 New York time) breaks the day's range so far
            local = idx.tz_convert("America/New_York")
            day = idx.floor("D")
            hi = df["high"].groupby(day).transform(lambda x: x.shift(1).cummax()).to_numpy(float)
            lo = df["low"].groupby(day).transform(lambda x: x.shift(1).cummin()).to_numpy(float)
            mins = local.hour * 60 + local.minute
            window = (mins >= 8 * 60 + 30) & (mins < 10 * 60 + 30)
        cc = c.to_numpy(float)
        prev = c.shift(1).to_numpy(float)
        if rule.endswith("LONG"):
            return np.asarray(window) & (cc > hi) & (prev <= hi)
        return np.asarray(window) & (cc < lo) & (prev >= lo)
    raise ValueError(rule)


def _trade(o, h, l, c, i, direction, stop, cost, n):
    """Enter at close[i]; returns (net return, outcome, exit index)."""
    e = c[i]
    tp = e * (1 + direction * TARGET)
    sl = e * (1 - direction * stop)
    end = min(n - 1, i + MAX_BARS)
    for j in range(i + 1, end + 1):
        hit_sl = l[j] <= sl if direction == 1 else h[j] >= sl
        hit_tp = h[j] >= tp if direction == 1 else l[j] <= tp
        if hit_sl:  # stop first when both are touched in one bar (gap through the stop exits at the open)
            px = o[j] if (o[j] - sl) * direction < 0 else sl
            return direction * (px - e) / e - cost, "STOP", j
        if hit_tp:
            return TARGET - cost, "TARGET", j
    return direction * (c[end] - e) / e - cost, "TIMEOUT", end


def _simulate(df, entries, direction, stop, cost):
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n, out, free = len(df), [], -1
    for i in entries:
        if i <= free or i >= n - 1:
            continue
        r, how, j = _trade(o, h, l, c, i, direction, stop, cost, n)
        out.append((i, r, how))
        free = j
    return out


def _ci(x, seed=7, n=2000, level=95.0):
    if len(x) < 10:
        return None
    rng = np.random.default_rng(seed)
    m = [float(np.mean(rng.choice(x, len(x)))) for _ in range(n)]
    a = (100 - level) / 2
    return [round(float(np.percentile(m, a)) * 100, 4), round(float(np.percentile(m, 100 - a)) * 100, 4)]


def backtest(df: pd.DataFrame, rule: str, stop: float, cost: float, tradable: Optional[np.ndarray] = None,
             ci_level: float = 95.0) -> ScalpReport:
    df = df.dropna(subset=["open", "high", "low", "close"])
    rep = ScalpReport(rule=rule, stop=stop, cost=cost)
    if len(df) < LOOKBACK * 30:
        rep.reason = "insufficient data"
        return rep
    sig = signals(df, rule)
    if tradable is not None:
        sig = sig & tradable
    direction = -1 if rule.endswith("SHORT") else 1
    trades = _simulate(df, np.flatnonzero(sig), direction, stop, cost)
    rep.period = f"{df.index[0].date()} -> {df.index[-1].date()}"
    if not trades:
        rep.reason = "no signal"
        return rep
    r = np.array([t[1] for t in trades])
    rep.trades = len(r)
    rep.targets = sum(t[2] == "TARGET" for t in trades)
    rep.stops = sum(t[2] == "STOP" for t in trades)
    rep.timeouts = sum(t[2] == "TIMEOUT" for t in trades)
    rep.win_rate = round(float((r > 0).mean()), 4)
    rep.avg_net_pct = round(float(r.mean()) * 100, 4)
    rep.avg_net_ci95 = _ci(r, level=ci_level)
    half = len(r) // 2
    rep.halves_pct = [round(float(r[:half].mean()) * 100, 4), round(float(r[half:].mean()) * 100, 4)] if half else None
    cut = df.index[int(len(df) * (1 - HOLDOUT_FRAC))]
    ho = np.array([t[1] for t in trades if df.index[t[0]] >= cut])
    rep.holdout_trades = len(ho)
    rep.holdout_avg_pct = round(float(ho.mean()) * 100, 4) if len(ho) else None
    eq = np.cumsum(r)
    rep.total_net_pct = round(float(eq[-1]) * 100, 2)
    rep.max_drawdown_pct = round(float(np.max(np.maximum.accumulate(eq) - eq)) * 100, 2)
    weeks = max((df.index[-1] - df.index[0]).days / 7, 1)
    rep.trades_per_week = round(len(r) / weeks, 2)
    # baseline: same exits, entries evenly spread over the eligible bars (same count)
    pool = np.flatnonzero(tradable) if tradable is not None else np.arange(LOOKBACK, len(df) - 1)
    pool = pool[pool >= LOOKBACK]
    if len(pool):
        base_idx = pool[np.linspace(0, len(pool) - 1, min(len(pool), len(r) * 3)).astype(int)]
        base = np.array([t[1] for t in _simulate(df, base_idx, direction, stop, cost)])
        if len(base):
            rep.baseline_avg_pct = round(float(base.mean()) * 100, 4)
            rng = np.random.default_rng(11)
            diffs = [float(np.mean(rng.choice(r, len(r))) - np.mean(rng.choice(base, len(base)))) for _ in range(2000)]
            a = (100 - ci_level) / 2
            rep.edge_ci95 = [round(float(np.percentile(diffs, a)) * 100, 4),
                             round(float(np.percentile(diffs, 100 - a)) * 100, 4)]
    ck = {
        "at least 100 trades": rep.trades >= 100,
        "average net CI above zero": bool(rep.avg_net_ci95 and rep.avg_net_ci95[0] > 0),
        "both halves positive": bool(rep.halves_pct and min(rep.halves_pct) > 0),
        "final holdout positive": bool(rep.holdout_avg_pct is not None and rep.holdout_trades >= 30
                                       and rep.holdout_avg_pct > 0),
        "beats evenly-timed entries (CI)": bool(rep.edge_ci95 and rep.edge_ci95[0] > 0),
    }
    rep.checks = ck
    rep.qualified = all(ck.values())
    rep.reason = "qualified" if rep.qualified else "failed: " + "; ".join(k for k, v in ck.items() if not v)
    return rep


def run_all(df: pd.DataFrame, cost: float, tradable: Optional[np.ndarray] = None, long_only: bool = False,
            rules: tuple = RULES, ci_level: float = 95.0) -> list[dict]:
    out = []
    for rule in rules:
        if long_only and rule.endswith("SHORT"):
            continue
        for stop in STOPS:
            out.append(asdict(backtest(df, rule, stop, cost, tradable, ci_level)))
    return out
