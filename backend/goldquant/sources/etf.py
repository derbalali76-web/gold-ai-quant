"""SPDR Gold Trust (GLD) daily holdings in tonnes — a public, daily, institutional flow series.

The issuer publishes a historical archive (XLSX) on spdrgoldshares.com. Holdings are updated after the New York
close, so every row gets published_at = date + 1 day 02:00 UTC (conservative). Columns are located by header
text (defensive parsing); verified=False until the live contract check passes. Personal-use terms apply.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pandas as pd

from ..providers.http import HttpClient, HttpError, RateLimiter

ARCHIVE_URL = "https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.xlsx"


def parse_archive(xlsx: bytes, fetched_at: datetime) -> list[dict]:
    raw = pd.read_excel(io.BytesIO(xlsx), header=None, sheet_name=0)
    hdr = None
    for i in range(min(30, len(raw))):
        row = [str(x) for x in raw.iloc[i].tolist()]
        if any("Date" in x for x in row) and any("Tonnes" in x for x in row):
            hdr = i
            break
    if hdr is None:
        raise ValueError("header with 'Date' and 'Tonnes' not found")
    df = raw.iloc[hdr + 1:].copy()
    df.columns = [str(c) for c in raw.iloc[hdr].tolist()]
    dcol = next(c for c in df.columns if "Date" in c)
    tcol = next(c for c in df.columns if "Tonnes" in c)
    df[dcol] = pd.to_datetime(df[dcol], errors="coerce", dayfirst=True)
    df[tcol] = pd.to_numeric(df[tcol].astype(str).str.replace(",", ""), errors="coerce")
    df = df.dropna(subset=[dcol, tcol]).sort_values(dcol)
    out = []
    for d, v in zip(df[dcol], df[tcol]):
        d = pd.Timestamp(d).tz_localize("UTC").normalize()
        out.append({"observed_at": d.isoformat(), "published_at": (d + timedelta(days=1, hours=2)).isoformat(),
                    "fetched_at": fetched_at.isoformat(), "value": float(v), "meta": {"unit": "tonnes"}})
    return out


def flows_as_of(rows_df: pd.DataFrame) -> dict | None:
    """rows_df: observations already filtered to published_at <= as_of (HistoryStore.load_observations_as_of)."""
    if len(rows_df) < 30:
        return None
    v = rows_df["value"].astype(float).to_numpy()
    d1, d5 = v[-1] - v[-2], v[-1] - v[-6]
    hist5 = pd.Series(v).diff(5).dropna().tail(250)
    z = float((d5 - hist5.mean()) / hist5.std()) if hist5.std() > 0 else 0.0
    return {"tonnes": float(v[-1]), "change_1d": round(float(d1), 2), "change_5d": round(float(d5), 2),
            "change_5d_z": round(z, 2), "as_of_date": str(rows_df["observed_at"].iloc[-1])[:10]}


class EtfSource:
    def __init__(self, http: HttpClient | None = None, url: str = ARCHIVE_URL):
        self.http = http or HttpClient(limiter=RateLimiter(calls=5, period=60.0), retries=1)
        self.url = url
        self.last_error: str | None = None

    def fetch(self) -> list[dict]:
        try:
            r = self.http.get(self.url)
            return parse_archive(r.content, datetime.now(timezone.utc))
        except (HttpError, ValueError, StopIteration) as exc:
            self.last_error = str(exc)
            raise
