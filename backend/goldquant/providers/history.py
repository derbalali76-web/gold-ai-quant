"""Local historical store (SQLite) so free-tier fetch limits do not cap the research history.

Every row keeps provider attribution and the time it was fetched. Only CLOSED bars are stored.
Point-in-time series (macro, COT, news) are stored with observed/published/fetched timestamps.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd

DDL = """
CREATE TABLE IF NOT EXISTS bars (
  provider TEXT, symbol TEXT, timeframe TEXT, open_time TEXT,
  open REAL, high REAL, low REAL, close REAL, volume REAL, fetched_at TEXT,
  PRIMARY KEY (provider, symbol, timeframe, open_time)
);
CREATE TABLE IF NOT EXISTS observations (
  source TEXT, series TEXT, observed_at TEXT, published_at TEXT, fetched_at TEXT, value REAL, meta TEXT,
  PRIMARY KEY (source, series, observed_at, published_at)
);
CREATE TABLE IF NOT EXISTS fetch_log (
  ts TEXT, source TEXT, ok INTEGER, latency_ms REAL, detail TEXT
);
"""


class HistoryStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._c = sqlite3.connect(self.path, check_same_thread=False)
        self._c.executescript(DDL)

    # ---------------- OHLC
    def upsert_bars(self, provider: str, symbol: str, timeframe: str, df: pd.DataFrame, fetched_at: datetime) -> int:
        rows = [(provider, symbol, timeframe, t.isoformat(), float(r.open), float(r.high), float(r.low),
                 float(r.close), float(r.get("tick_volume", 0.0) or 0.0), fetched_at.isoformat())
                for t, r in df.iterrows()]
        with self._lock:
            self._c.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            self._c.commit()
        return len(rows)

    def load_bars(self, provider: str, symbol: str, timeframe: str, limit: int = 100000) -> pd.DataFrame:
        with self._lock:
            rows = self._c.execute(
                "SELECT open_time, open, high, low, close, volume FROM bars WHERE provider=? AND symbol=? AND timeframe=? "
                "ORDER BY open_time DESC LIMIT ?", (provider, symbol, timeframe, limit)).fetchall()
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "tick_volume"],
                                index=pd.DatetimeIndex([], tz="UTC"))
        df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "tick_volume"])
        df.index = pd.to_datetime(df.pop("t"), utc=True)
        return df.sort_index()

    def count_bars(self, provider: str, symbol: str, timeframe: str) -> int:
        with self._lock:
            return self._c.execute("SELECT COUNT(*) FROM bars WHERE provider=? AND symbol=? AND timeframe=?",
                                   (provider, symbol, timeframe)).fetchone()[0]

    # ---------------- point-in-time observations
    def upsert_observations(self, source: str, series: str, rows: list[dict]) -> int:
        vals = [(source, series, r["observed_at"], r["published_at"], r["fetched_at"], r["value"],
                 json.dumps(r.get("meta", {}), ensure_ascii=False)) for r in rows]
        with self._lock:
            self._c.executemany("INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?,?)", vals)
            self._c.commit()
        return len(vals)

    def load_observations_as_of(self, source: str, series: str, as_of: datetime) -> pd.DataFrame:
        """Only observations PUBLISHED at or before as_of (prevents look-ahead / revision leakage)."""
        with self._lock:
            rows = self._c.execute(
                "SELECT observed_at, published_at, value FROM observations WHERE source=? AND series=? AND published_at<=? "
                "ORDER BY observed_at", (source, series, as_of.isoformat())).fetchall()
        return pd.DataFrame(rows, columns=["observed_at", "published_at", "value"])

    # ---------------- monitoring
    def log_fetch(self, ts: datetime, source: str, ok: bool, latency_ms: float | None, detail: str) -> None:
        with self._lock:
            self._c.execute("INSERT INTO fetch_log VALUES (?,?,?,?,?)", (ts.isoformat(), source, int(ok), latency_ms, detail[:300]))
            self._c.commit()

    def recent_fetches(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._c.execute("SELECT ts, source, ok, latency_ms, detail FROM fetch_log ORDER BY ts DESC LIMIT ?",
                                   (limit,)).fetchall()
        return [dict(zip(["ts", "source", "ok", "latency_ms", "detail"], r)) for r in rows]
