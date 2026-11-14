"""Dukascopy public historical datafeed importer (free download; personal research use — check their terms).

Daily 1-minute BID candle files:
    https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YYYY}/{MM-1:02d}/{DD:02d}/BID_candles_min_1.bi5
Each file is LZMA-compressed; records are 24 bytes big-endian:
    uint32 seconds-from-midnight-UTC, uint32 open, uint32 close, uint32 low, uint32 high, float32 volume
Prices are integers scaled by a symbol-specific point; the scale is detected from a plausibility range and the
detection is recorded, so a wrong assumption fails loudly instead of silently corrupting prices.
Volume is Dukascopy's own tick volume — NOT the global market volume.
"""
from __future__ import annotations

import lzma
import struct
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import numpy as np
import pandas as pd

from .http import HttpClient, HttpError, RateLimiter

BASE = "https://datafeed.dukascopy.com/datafeed"
PLAUSIBLE = {"XAUUSD": (200.0, 20000.0), "XAGUSD": (2.0, 500.0), "EURUSD": (0.5, 2.5), "USDJPY": (50.0, 400.0),
             # cross-asset context (ranges < 10x wide so the price scale is unambiguous)
             "DOLLARIDXUSD": (60.0, 160.0), "USA500IDXUSD": (900.0, 9000.0), "USTBONDTRUSD": (70.0, 250.0)}
SCALES = (100000.0, 1000.0, 100.0, 10.0)
REC = struct.Struct(">5If")


def day_url(symbol: str, d: date) -> str:
    return f"{BASE}/{symbol}/{d.year:04d}/{d.month - 1:02d}/{d.day:02d}/BID_candles_min_1.bi5"


def detect_scale(symbol: str, raw_close: np.ndarray) -> float:
    lo, hi = PLAUSIBLE.get(symbol, (0.0, float("inf")))
    med = float(np.median(raw_close))
    for s in SCALES:
        if lo <= med / s <= hi:
            return s
    raise ValueError(f"cannot determine price scale for {symbol} (median raw {med})")


def parse_day(payload: bytes, symbol: str, d: date, scale: float | None = None) -> pd.DataFrame:
    if not payload:
        return pd.DataFrame(columns=["open", "high", "low", "close", "tick_volume"])
    raw = lzma.decompress(payload)
    if len(raw) % REC.size:
        raise ValueError("corrupt candle file (size not a multiple of 24)")
    rows = np.array(list(REC.iter_unpack(raw)), dtype=float)
    if not len(rows):
        return pd.DataFrame(columns=["open", "high", "low", "close", "tick_volume"])
    sc = scale or detect_scale(symbol, rows[:, 2])
    base = pd.Timestamp(d, tz="UTC")
    idx = base + pd.to_timedelta(rows[:, 0].astype(int), unit="s")
    df = pd.DataFrame({"open": rows[:, 1] / sc, "high": rows[:, 4] / sc, "low": rows[:, 3] / sc,
                       "close": rows[:, 2] / sc, "tick_volume": rows[:, 5]}, index=idx)
    df = df[df["tick_volume"] > 0]  # Dukascopy fills closed-market minutes with flat zero-volume candles
    df.attrs["scale"] = sc
    return df


def to_timeframe(m1: pd.DataFrame, minutes: int) -> pd.DataFrame:
    return m1.resample(f"{minutes}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "tick_volume": "sum"}).dropna(subset=["open"])


class DukascopyImporter:
    def __init__(self, http: HttpClient | None = None):
        # Measured on GitHub runners: at 60 req/min Dukascopy answers HTTP 503 and lets TLS handshakes time out on about
        # half the days. Slower, with longer timeouts and patient retries, the same budget fetches more data.
        self.http = http or HttpClient(limiter=RateLimiter(calls=25, period=60.0), retries=4, backoff=4.0, timeout=30.0)
        self.errors: list[str] = []

    def fetch_day(self, symbol: str, d: date) -> pd.DataFrame:
        try:
            r = self.http.get(day_url(symbol, d))
        except HttpError as exc:
            if exc.status == 404:
                return pd.DataFrame(columns=["open", "high", "low", "close", "tick_volume"])
            self.errors.append(f"{symbol} {d}: {exc}")
            raise
        return parse_day(r.content, symbol, d)

    def fetch_range(self, symbol: str, start: date, end: date, second_pass_wait: float = 60.0) -> pd.DataFrame:
        """Days that fail (throttling / timeouts) are retried once more after a pause, so a month is not left
        with holes; days still failing are listed in self.errors and fetched again by the next backfill run."""
        parts, failed = [], []
        d = start
        while d <= end:
            if d.weekday() != 5:  # Saturdays are always empty
                try:
                    parts.append(self.fetch_day(symbol, d))
                except HttpError:
                    failed.append(d)
            d += timedelta(days=1)
        if failed:
            self.http.sleep(second_pass_wait)
            for d in failed:
                try:
                    parts.append(self.fetch_day(symbol, d))
                    self.errors = [e for e in self.errors if not e.startswith(f"{symbol} {d}:")]
                except HttpError:
                    pass
        parts = [p for p in parts if len(p)]
        return pd.concat(parts).sort_index() if parts else pd.DataFrame()
