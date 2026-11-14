"""Interchangeable provider interfaces with explicit provenance metadata."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

TIMEFRAMES = {"M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
OHLC_COLUMNS = ["open", "high", "low", "close", "tick_volume"]


@dataclass(frozen=True)
class ProviderMeta:
    name: str
    license_note: str
    cost: str  # always "FREE" for enabled providers
    update_interval_seconds: int
    timezone: str
    spot_or_proxy: str  # SPOT | PROXY | SYNTHETIC
    requires_key: bool
    verified: bool  # True only after a live contract test passed on the user's machine
    typical_latency_ms: Optional[int] = None
    limits_note: str = ""


@dataclass
class Quote:
    price: float
    observed_at: datetime  # time the provider says the price was valid
    fetched_at: datetime
    provider: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    published_at: Optional[datetime] = None
    warnings: list = field(default_factory=list)  # e.g. cross-source disagreement

    def age_seconds(self, now: datetime) -> float:
        return (now - self.observed_at).total_seconds()


@dataclass
class Bars:
    """OHLC bars indexed by bar OPEN time (UTC). A bar is only usable once open+timeframe <= as_of."""
    timeframe: str
    df: pd.DataFrame
    provider: str
    fetched_at: datetime
    meta: dict = field(default_factory=dict)

    def validate(self) -> None:
        df = self.df
        missing = [c for c in OHLC_COLUMNS[:4] if c not in df.columns]
        if missing:
            raise ValueError(f"missing columns {missing}")
        if df.index.tz is None or str(df.index.tz) != "UTC":
            raise ValueError("index must be tz-aware UTC")
        if not df.index.is_monotonic_increasing or df.index.has_duplicates:
            raise ValueError("index must be strictly increasing")
        bad = (df["high"] < df[["open", "close"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1))
        if bad.any():
            raise ValueError(f"{int(bad.sum())} bars violate OHLC invariants")
        if (df[["open", "high", "low", "close"]] <= 0).any().any():
            raise ValueError("non-positive prices")


class MarketDataProvider(ABC):
    meta: ProviderMeta

    @abstractmethod
    def quote(self, as_of: datetime) -> Optional[Quote]:
        ...

    @abstractmethod
    def bars(self, timeframe: str, as_of: datetime, count: int) -> Optional[Bars]:
        """Return only bars fully CLOSED at or before as_of (no look-ahead)."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def market_closed_mask(index: pd.DatetimeIndex) -> "pd.Series | object":
    """True for bar OPEN times inside the weekly close: Friday 17:00 -> Sunday 18:00 New York time (DST-aware,
    i.e. Fri 21:00 -> Sun 22:00 UTC in summer, Fri 22:00 -> Sun 23:00 UTC in winter).
    Some feeds keep printing flat quotes over the weekend; those are not market prices."""
    n = index.tz_convert("America/New_York")
    dow, hour = n.day_of_week, n.hour
    return (dow == 5) | ((dow == 4) & (hour >= 17)) | ((dow == 6) & (hour < 18))


def closed_bars(df: pd.DataFrame, timeframe: str, as_of: datetime) -> pd.DataFrame:
    """Bars that are complete at as_of, without weekend prints."""
    minutes = TIMEFRAMES[timeframe]
    close_time = df.index + pd.Timedelta(minutes=minutes)
    keep = close_time <= pd.Timestamp(as_of)
    if len(df):
        keep = keep & ~market_closed_mask(df.index)
    return df[keep]
