"""Twelve Data adapter for XAU/USD (free Basic plan: 8 credits/min, 800/day; personal non-display use).

- Quote: last CLOSED 1-minute bar of /time_series (its close and close-time). The /price endpoint carries no
  timestamp, so it is not used: a price without a time cannot be checked for staleness.
- Bars: /time_series with timezone=UTC; the forming (not yet closed) bar is dropped.
- M30 is resampled locally from M15 to save credits.
- Fetched bars are merged into the local HistoryStore so the research history grows past the 5000-bar cap.
verified=False until tools/live_contract_check.py passes on the user's machine.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from .base import Bars, MarketDataProvider, ProviderMeta, Quote, closed_bars, market_closed_mask, utcnow
from .history import HistoryStore
from .http import HttpClient, HttpError, RateLimiter

BASE = "https://api.twelvedata.com"
SYMBOL = "XAU/USD"
INTERVALS = {"M1": "1min", "M15": "15min", "H1": "1h", "H4": "4h", "D1": "1day"}
TTL = {"M15": timedelta(minutes=15), "H1": timedelta(hours=1), "H4": timedelta(hours=4), "D1": timedelta(hours=6)}


class ProviderError(Exception):
    pass


def parse_time_series(text: str) -> pd.DataFrame:
    """Parse a /time_series payload (requested with timezone=UTC) into a UTC-indexed OHLC frame."""
    try:
        o = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError("invalid JSON") from exc
    if o.get("status") == "error":
        raise ProviderError(f"twelvedata error {o.get('code')}: {o.get('message', '')[:120]}")
    vals = o.get("values")
    if not isinstance(vals, list) or not vals:
        raise ProviderError("no values")
    df = pd.DataFrame(vals)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="raise")
    df["tick_volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0) if "volume" in df else 0.0
    idx = pd.to_datetime(df["datetime"], utc=True)  # naive strings are interpreted as UTC (we request UTC)
    out = df[["open", "high", "low", "close", "tick_volume"]].set_index(idx).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out.index.name = None
    return out


class TwelveDataProvider(MarketDataProvider):
    meta = ProviderMeta(
        name="TwelveData", license_note="Free Basic plan: personal, internal non-display use only", cost="FREE",
        update_interval_seconds=60, timezone="UTC", spot_or_proxy="SPOT", requires_key=True, verified=False,
        typical_latency_ms=None, limits_note="8 credits/min, 800/day; outputsize<=5000")

    def __init__(self, api_key: str | None = None, history: HistoryStore | None = None,
                 http: HttpClient | None = None, clock=utcnow):
        self.api_key = api_key or os.environ.get("TWELVEDATA_API_KEY", "")
        self.history = history or HistoryStore()
        self.http = http or HttpClient(limiter=RateLimiter(calls=7, period=60.0))
        self.clock = clock
        self._last_fetch: dict[str, datetime] = {}
        self.last_error: Optional[str] = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _series(self, tf: str, outputsize: int) -> pd.DataFrame:
        params = {"symbol": SYMBOL, "interval": INTERVALS[tf], "outputsize": outputsize, "timezone": "UTC",
                  "order": "asc", "apikey": self.api_key}
        now = self.clock()
        try:
            r = self.http.get(f"{BASE}/time_series", params)
            df = parse_time_series(r.text)
            self.history.log_fetch(now, f"{self.meta.name}:{tf}", True, r.elapsed_ms, f"{len(df)} bars")
            return df
        except (HttpError, ProviderError) as exc:
            self.last_error = str(exc)
            self.history.log_fetch(now, f"{self.meta.name}:{tf}", False, None, str(exc))
            raise

    def quote(self, as_of: datetime) -> Optional[Quote]:
        if not self.configured:
            return None
        try:
            df = self._series("M1", 3)
        except (HttpError, ProviderError):
            return None
        df = df[(df.index + pd.Timedelta(minutes=1) <= pd.Timestamp(as_of)) & ~market_closed_mask(df.index)]
        if df.empty:
            # weekend: the feed's prints are not market prices; report the last session's close at its real time
            h = closed_bars(self.history.load_bars(self.meta.name, SYMBOL, "M15"), "M15", as_of)
            if h.empty:
                return None
            t = (h.index[-1] + pd.Timedelta(minutes=15)).to_pydatetime()
            return Quote(price=round(float(h["close"].iloc[-1]), 2), observed_at=t, fetched_at=self.clock(),
                         provider=self.meta.name)
        t = (df.index[-1] + pd.Timedelta(minutes=1)).to_pydatetime()
        return Quote(price=round(float(df["close"].iloc[-1]), 2), observed_at=t, fetched_at=self.clock(),
                     provider=self.meta.name)

    def refresh(self, tf: str, as_of: datetime) -> None:
        """Fetch new bars for tf if the cached copy is older than one bar; merge into history."""
        last = self._last_fetch.get(tf)
        if last is not None and as_of - last < TTL[tf]:
            return
        have = self.history.count_bars(self.meta.name, SYMBOL, tf)
        size = 5000 if have < 1000 else (40 if tf == "D1" else 300)
        df = closed_bars(self._series(tf, size), tf, as_of)
        self.history.upsert_bars(self.meta.name, SYMBOL, tf, df, self.clock())
        self._last_fetch[tf] = as_of

    def bars(self, timeframe: str, as_of: datetime, count: int) -> Optional[Bars]:
        if not self.configured:
            return None
        src = "M15" if timeframe == "M30" else timeframe
        try:
            self.refresh(src, as_of)
        except (HttpError, ProviderError):
            pass  # fall back to stored history; freshness is judged separately from the quote
        df = self.history.load_bars(self.meta.name, SYMBOL, src)
        if timeframe == "M30" and not df.empty:
            df = df.resample("30min", label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "tick_volume": "sum"}).dropna()
        df = closed_bars(df, timeframe, as_of).tail(count)
        if df.empty:
            return None
        return Bars(timeframe, df, self.meta.name, self.clock())
