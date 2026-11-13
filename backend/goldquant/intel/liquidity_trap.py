"""Liquidity Trap Engine (V2 #3): sweeps of recent extremes, failed breakouts and wick anomalies.

All of this is INFERENCE from price shape. Spot gold has no consolidated order book or true volume, so
nothing here claims to see stop orders or institutional flow.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..features import atr, robust_z


@dataclass
class TrapEvent:
    kind: str  # SWEEP_LOW_RECLAIM | SWEEP_HIGH_REJECT | FAILED_BREAKOUT_UP | FAILED_BREAKOUT_DOWN | WICK_ANOMALY
    bars_ago: int
    level: float
    implied_sign: int  # +1 bullish implication, -1 bearish
    text_ar: str


def scan(df: pd.DataFrame, lookback: int = 20, recent: int = 3) -> list[TrapEvent]:
    if len(df) < lookback + recent + 5:
        return []
    h, l, c, o = (df[k].to_numpy() for k in ("high", "low", "close", "open"))
    a = atr(df).to_numpy()
    prior_hi = pd.Series(h).shift(1).rolling(lookback).max().to_numpy()
    prior_lo = pd.Series(l).shift(1).rolling(lookback).min().to_numpy()
    rng = np.maximum(h - l, 1e-12)
    upper_wick, lower_wick = h - np.maximum(o, c), np.minimum(o, c) - l
    wz_u = robust_z(pd.Series(upper_wick / rng), 200).to_numpy()
    wz_l = robust_z(pd.Series(lower_wick / rng), 200).to_numpy()
    out: list[TrapEvent] = []
    n = len(df)
    for i in range(n - recent, n):
        ago = n - 1 - i
        tol = 0.05 * a[i] if a[i] == a[i] else 0.0
        if l[i] < prior_lo[i] - tol and c[i] > prior_lo[i]:
            out.append(TrapEvent("SWEEP_LOW_RECLAIM", ago, round(prior_lo[i], 2), +1,
                                 f"كسر قاع آخر {lookback} شمعة ثم إغلاق فوقه (سحب سيولة محتمل — استدلال)"))
        if h[i] > prior_hi[i] + tol and c[i] < prior_hi[i]:
            out.append(TrapEvent("SWEEP_HIGH_REJECT", ago, round(prior_hi[i], 2), -1,
                                 f"تجاوز قمة آخر {lookback} شمعة ثم إغلاق تحتها (سحب سيولة محتمل — استدلال)"))
        if i >= 1 and c[i - 1] > prior_hi[i - 1] and c[i] < prior_hi[i - 1]:
            out.append(TrapEvent("FAILED_BREAKOUT_UP", ago, round(prior_hi[i - 1], 2), -1, "اختراق صاعد فشل في الشمعة التالية"))
        if i >= 1 and c[i - 1] < prior_lo[i - 1] and c[i] > prior_lo[i - 1]:
            out.append(TrapEvent("FAILED_BREAKOUT_DOWN", ago, round(prior_lo[i - 1], 2), +1, "اختراق هابط فشل في الشمعة التالية"))
        if wz_u[i] == wz_u[i] and wz_u[i] > 3.5:
            out.append(TrapEvent("WICK_ANOMALY", ago, round(h[i], 2), -1, "ذيل علوي طويل بشكل شاذ إحصائياً"))
        if wz_l[i] == wz_l[i] and wz_l[i] > 3.5:
            out.append(TrapEvent("WICK_ANOMALY", ago, round(l[i], 2), +1, "ذيل سفلي طويل بشكل شاذ إحصائياً"))
    return out


def event_series(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Vectorised +1/-1/0 sweep indicator per bar (for research / information-value tests)."""
    h, l, c = df["high"], df["low"], df["close"]
    a = atr(df)
    ph, pl = h.shift(1).rolling(lookback).max(), l.shift(1).rolling(lookback).min()
    bull = (l < pl - 0.05 * a) & (c > pl)
    bear = (h > ph + 0.05 * a) & (c < ph)
    return bull.astype(int) - bear.astype(int)
