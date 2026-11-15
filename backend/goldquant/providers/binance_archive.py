"""Binance public data archive (data.binance.vision): free monthly ZIP files, no key, no throttling.

Spot klines carry REAL exchange volume and taker-buy volume (who initiated the trades) — what spot gold lacks.
USD-M perpetual funding-rate history is published the same way.
Note: Binance blocks its trading API (api.binance.com) from US IPs (HTTP 451); the archive and the public
market-data mirror data-api.binance.vision are used instead. Since 2025 spot files use microsecond timestamps.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date
from typing import Optional

import pandas as pd

from .http import HttpClient, HttpError, RateLimiter

BASE = "https://data.binance.vision/data"
LIVE = "https://data-api.binance.vision/api/v3"
CRYPTO = {"BTCUSDT": "BTC/USD", "ETHUSDT": "ETH/USD", "SOLUSDT": "SOL/USD"}
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades",
              "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def _ts(v: pd.Series) -> pd.DatetimeIndex:
    v = pd.to_numeric(v, errors="coerce")
    unit = "us" if v.dropna().median() > 1e14 else "ms"  # spot switched to microseconds in 2025
    return pd.to_datetime(v, unit=unit, utc=True)


def parse_klines_zip(payload: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        raw = z.read(z.namelist()[0]).decode("utf-8")
    first = raw.split("\n", 1)[0]
    header = 0 if first[:1].isalpha() else None
    df = pd.read_csv(io.StringIO(raw), header=header, names=None if header == 0 else KLINE_COLS)
    df.columns = [c.strip().lower() for c in df.columns]
    if "count" in df.columns and "trades" not in df.columns:
        df = df.rename(columns={"count": "trades"})
    out = pd.DataFrame({k: pd.to_numeric(df[k], errors="coerce") for k in
                        ("open", "high", "low", "close", "volume", "taker_buy_volume")})
    out.index = _ts(df["open_time"])
    out.index.name = "open_time"
    out = out.dropna(subset=["open", "high", "low", "close"])
    return out[~out.index.duplicated()].sort_index()


def parse_funding_zip(payload: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        raw = z.read(z.namelist()[0]).decode("utf-8")
    df = pd.read_csv(io.StringIO(raw))
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = "calc_time" if "calc_time" in df.columns else df.columns[0]
    rcol = "last_funding_rate" if "last_funding_rate" in df.columns else df.columns[-1]
    out = pd.DataFrame({"funding": pd.to_numeric(df[rcol], errors="coerce")})
    out.index = _ts(df[tcol])
    return out.dropna().sort_index()


def parse_metrics_zip(payload: bytes) -> pd.DataFrame:
    """USD-M futures 5-minute metrics -> hourly (last value in each hour, stamped at the hour's OPEN like klines,
    so the value is known at that bar's close)."""
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        raw = z.read(z.namelist()[0]).decode("utf-8")
    df = pd.read_csv(io.StringIO(raw))
    df.columns = [c.strip().lower() for c in df.columns]
    t = pd.to_datetime(df["create_time"], utc=True)
    keep = {"sum_open_interest": "oi", "sum_toptrader_long_short_ratio": "top_ls_ratio",
            "sum_taker_long_short_vol_ratio": "taker_ls_ratio"}
    out = pd.DataFrame({v: pd.to_numeric(df[k], errors="coerce") for k, v in keep.items() if k in df.columns})
    out.index = t
    # a 5-min snapshot stamped hh:05..hh+1:00 belongs to the hour ending hh+1:00 -> bar opened at hh:00
    out = out.groupby((out.index - pd.Timedelta(seconds=1)).floor("h")).last()
    out.index.name = "open_time"
    return out.dropna(how="all")


def months(start: date, end: date) -> list[tuple[int, int]]:
    y, m, out = start.year, start.month, []
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def parse_book_depth_zip(payload: bytes) -> pd.DataFrame:
    """USD-M futures order-book depth snapshots (data.binance.vision .../bookDepth): cumulative notional within
    +-p % of the price. Returns one row per snapshot time with bid/ask notional at 1, 2 and 5 %."""
    import io as _io
    import zipfile as _zf
    with _zf.ZipFile(_io.BytesIO(payload)) as z:
        name = z.namelist()[0]
        df = pd.read_csv(z.open(name))
    cols = {c.lower(): c for c in df.columns}
    t = cols.get("timestamp") or df.columns[0]
    pc = cols.get("percentage") or df.columns[1]
    nc = cols.get("notional") or df.columns[3]
    ts = pd.to_datetime(df[t], utc=True, errors="coerce")
    if ts.isna().all():  # epoch milliseconds
        ts = pd.to_datetime(pd.to_numeric(df[t], errors="coerce"), unit="ms", utc=True)
    d = pd.DataFrame({"t": ts, "p": pd.to_numeric(df[pc], errors="coerce"),
                      "n": pd.to_numeric(df[nc], errors="coerce")}).dropna()
    out = {}
    for lvl in (1, 2, 5):
        b = d[d["p"] == -lvl].groupby("t")["n"].last()
        a = d[d["p"] == lvl].groupby("t")["n"].last()
        out[f"bid{lvl}"], out[f"ask{lvl}"] = b, a
    o = pd.DataFrame(out).dropna().sort_index()
    o.index.name = "time"
    return o


class BinanceArchive:
    def __init__(self, http: Optional[HttpClient] = None):
        self.http = http or HttpClient(limiter=RateLimiter(calls=120, period=60.0), retries=3, backoff=2.0, timeout=60.0)
        self.errors: list[str] = []

    def _get(self, url: str) -> Optional[bytes]:
        try:
            return self.http.get(url).content
        except HttpError as exc:
            if exc.status == 404:  # month not published (yet) / symbol not listed then
                return None
            self.errors.append(f"{url}: {exc}")
            return None

    def klines_month(self, symbol: str, interval: str, y: int, m: int) -> pd.DataFrame:
        p = self._get(f"{BASE}/spot/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{y:04d}-{m:02d}.zip")
        return parse_klines_zip(p) if p else pd.DataFrame()

    def klines_day(self, symbol: str, interval: str, d: date) -> pd.DataFrame:
        p = self._get(f"{BASE}/spot/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{d.isoformat()}.zip")
        return parse_klines_zip(p) if p else pd.DataFrame()

    def metrics_day(self, symbol: str, d: date) -> pd.DataFrame:
        p = self._get(f"{BASE}/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{d.isoformat()}.zip")
        return parse_metrics_zip(p) if p else pd.DataFrame()

    def book_depth_day(self, symbol: str, d: date) -> pd.DataFrame:
        p = self._get(f"{BASE}/futures/um/daily/bookDepth/{symbol}/{symbol}-bookDepth-{d.isoformat()}.zip")
        return parse_book_depth_zip(p) if p else pd.DataFrame()

    def funding_month(self, symbol: str, y: int, m: int) -> pd.DataFrame:
        p = self._get(f"{BASE}/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{y:04d}-{m:02d}.zip")
        return parse_funding_zip(p) if p else pd.DataFrame()
