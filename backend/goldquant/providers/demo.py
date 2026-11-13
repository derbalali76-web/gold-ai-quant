"""Deterministic SYNTHETIC XAU/USD-like dataset for DEMO mode and tests.

The prices are NOT market data. They come from a seeded regime-switching process with volatility
clustering, so the engine can be exercised end-to-end reproducibly. Every output is labelled SYNTHETIC.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd

from .base import Bars, MarketDataProvider, ProviderMeta, Quote, TIMEFRAMES, closed_bars

DEMO_SEED = 20261112
DEMO_END = datetime(2025, 12, 31, 16, 0, tzinfo=timezone.utc)
DEMO_DAYS = 160
BASE_PRICE = 2000.0

# regime: (drift per minute in log-return, base vol per minute, mean-reversion strength)
REGIMES = {
    "trend_up": (4.0e-6, 1.6e-4, 0.0),
    "trend_down": (-4.0e-6, 1.7e-4, 0.0),
    "range": (0.0, 1.2e-4, 0.002),
    "shock": (0.0, 4.0e-4, 0.0),
}
TRANSITION = {  # per-M15-bar switch probabilities
    "trend_up": {"trend_up": 0.994, "range": 0.004, "trend_down": 0.001, "shock": 0.001},
    "trend_down": {"trend_down": 0.994, "range": 0.004, "trend_up": 0.001, "shock": 0.001},
    "range": {"range": 0.993, "trend_up": 0.003, "trend_down": 0.003, "shock": 0.001},
    "shock": {"shock": 0.90, "range": 0.06, "trend_up": 0.02, "trend_down": 0.02},
}


def _market_open(ts: pd.DatetimeIndex) -> np.ndarray:
    """Approximate spot-gold weekly session: closed Fri 21:00 UTC -> Sun 22:00 UTC, daily break 21:00-22:00."""
    dow, hour = ts.dayofweek, ts.hour
    weekend = (dow == 5) | ((dow == 4) & (hour >= 21)) | ((dow == 6) & (hour < 22))
    daily_break = hour == 21
    return ~(weekend | daily_break)


@lru_cache(maxsize=4)
def generate_m1(seed: int = DEMO_SEED, days: int = DEMO_DAYS, end: datetime = DEMO_END) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start = end - timedelta(days=days)
    idx = pd.date_range(start, end, freq="1min", inclusive="left", tz="UTC")
    idx = idx[_market_open(idx)]
    n = len(idx)
    names = list(REGIMES)
    state = "range"
    states = np.empty(n, dtype=object)
    rets = np.empty(n)
    logp = np.log(BASE_PRICE)
    anchor = logp
    sigma2 = REGIMES[state][1] ** 2
    eps_all = rng.standard_t(5, size=n) / np.sqrt(5 / 3)
    u_all = rng.random(n)
    cum = {k: np.cumsum([TRANSITION[k].get(j, 0.0) for j in names]) for k in names}
    prev_r = 0.0
    for i in range(n):
        if i % 15 == 0:
            new_state = names[min(int(np.searchsorted(cum[state], u_all[i])), len(names) - 1)]
            if new_state != state and new_state == "range":
                anchor = logp
            state = new_state
        drift, base_vol, mr = REGIMES[state]
        # GARCH(1,1)-style clustering around the regime base variance
        sigma2 = 0.02 * base_vol ** 2 + 0.03 * prev_r ** 2 + 0.95 * sigma2
        r = drift + mr * (anchor - logp) + np.sqrt(sigma2) * eps_all[i]
        rets[i] = r
        prev_r = r
        logp += r
        states[i] = state
    close = BASE_PRICE * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[BASE_PRICE], close[:-1]])
    wick = np.abs(rng.normal(0, 0.35, n)) * np.abs(rets) * close
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.35, n)) * np.abs(rets) * close
    vol = rng.poisson(40 * (1 + 4 * np.abs(rets) / 1.5e-4)).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "tick_volume": vol, "regime_truth": states}, index=idx)


def resample(m1: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    rule = f"{TIMEFRAMES[timeframe]}min"
    agg = m1.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "tick_volume": "sum"})
    return agg.dropna(subset=["open"])


@lru_cache(maxsize=16)
def _bars_cached(timeframe: str, seed: int) -> pd.DataFrame:
    return resample(generate_m1(seed), timeframe)


class DemoProvider(MarketDataProvider):
    meta = ProviderMeta(
        name="DEMO-SYNTHETIC", license_note="Generated locally; not market data", cost="FREE",
        update_interval_seconds=60, timezone="UTC", spot_or_proxy="SYNTHETIC", requires_key=False,
        verified=True, typical_latency_ms=0, limits_note="Synthetic, deterministic (seed fixed)")

    def __init__(self, seed: int = DEMO_SEED):
        self.seed = seed

    def m1(self) -> pd.DataFrame:
        return generate_m1(self.seed)

    def default_as_of(self) -> datetime:
        last = self.m1().index[-1]
        return (last + pd.Timedelta(minutes=1)).to_pydatetime()

    def quote(self, as_of: datetime) -> Optional[Quote]:
        m1 = self.m1()
        past = m1[m1.index + pd.Timedelta(minutes=1) <= pd.Timestamp(as_of)]
        if past.empty:
            return None
        ts = (past.index[-1] + pd.Timedelta(minutes=1)).to_pydatetime()
        return Quote(price=round(float(past["close"].iloc[-1]), 2), observed_at=ts, fetched_at=as_of,
                     provider=self.meta.name)

    def bars(self, timeframe: str, as_of: datetime, count: int) -> Optional[Bars]:
        df = closed_bars(_bars_cached(timeframe, self.seed), timeframe, as_of).tail(count)
        if df.empty:
            return None
        return Bars(timeframe=timeframe, df=df.copy(), provider=self.meta.name, fetched_at=as_of)
