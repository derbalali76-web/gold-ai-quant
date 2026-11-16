"""FRED macro series via the public fredgraph.csv endpoint (no key).

Point-in-time discipline: FRED returns the LATEST vintage. Each observation therefore gets a conservative
`published_at` (observation date + typical release lag) and the metadata flag `revision_risk=True` for
revisable series. Features may only use rows whose published_at <= as_of (HistoryStore.load_observations_as_of).
Exact vintages need ALFRED (free API key) — planned; until then revision leakage is documented, not hidden.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd

from ..providers.http import HttpClient, HttpError, RateLimiter

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
# Official API (free key; FRED's terms allow automated access only through it). With a key, revisable series come
# from ALFRED as FIRST RELEASES (output_type=4) and published_at is the real vintage date: no revision leakage.
API_URL = "https://api.stlouisfed.org/fred/series/observations"
RELEASE_HOUR_UTC = 16  # US data are released 08:30-10:00 ET; 16:00 UTC is a conservative "available by" time


@dataclass(frozen=True)
class SeriesSpec:
    series: str
    name_ar: str
    lag: timedelta  # conservative observation -> availability lag
    revisable: bool


SERIES = {
    "DGS10": SeriesSpec("DGS10", "عائد سندات الخزانة 10 سنوات", timedelta(days=1, hours=22), False),
    "DFII10": SeriesSpec("DFII10", "العائد الحقيقي 10 سنوات (TIPS)", timedelta(days=1, hours=22), False),
    "DTWEXBGS": SeriesSpec("DTWEXBGS", "مؤشر الدولار الواسع (Fed)", timedelta(days=8), True),
    "DFF": SeriesSpec("DFF", "سعر الفائدة الفعلي للفيدرالي", timedelta(days=1, hours=22), False),
    "GVZCLS": SeriesSpec("GVZCLS", "مؤشر تقلب الذهب المتوقع (CBOE GVZ)", timedelta(days=1, hours=22), False),
    "CPIAUCSL": SeriesSpec("CPIAUCSL", "مؤشر أسعار المستهلك", timedelta(days=45), True),
    "PCEPI": SeriesSpec("PCEPI", "مؤشر أسعار PCE", timedelta(days=60), True),
    "PAYEMS": SeriesSpec("PAYEMS", "الوظائف غير الزراعية", timedelta(days=40), True),
    "UNRATE": SeriesSpec("UNRATE", "معدل البطالة", timedelta(days=40), True),
}


def parse_fredgraph_csv(text: str, spec: SeriesSpec, fetched_at: datetime) -> list[dict]:
    df = pd.read_csv(io.StringIO(text))
    date_col = df.columns[0]  # 'observation_date' (current) or 'DATE' (older format)
    if spec.series not in df.columns:
        raise ValueError(f"series column {spec.series} missing")
    df[spec.series] = pd.to_numeric(df[spec.series], errors="coerce")  # '.' = missing
    df = df.dropna(subset=[spec.series])
    out = []
    for d, v in zip(pd.to_datetime(df[date_col], utc=True), df[spec.series]):
        pub = (d + spec.lag).to_pydatetime()
        out.append({"observed_at": d.isoformat(), "published_at": pub.isoformat(), "fetched_at": fetched_at.isoformat(),
                    "value": float(v), "meta": {"revision_risk": spec.revisable, "publication_time": "approximate"}})
    return out


def parse_api_json(text: str, spec: SeriesSpec, fetched_at: datetime, vintages: bool) -> list[dict]:
    """FRED API observations. With vintages (ALFRED first release) published_at = realtime_start at RELEASE_HOUR_UTC
    (the day the value first became public); otherwise the conservative lag of the series."""
    import json
    rows = json.loads(text).get("observations")
    if not isinstance(rows, list):
        raise ValueError("unexpected FRED API payload")
    out = []
    for o in rows:
        try:
            v = float(o["value"])
        except (KeyError, TypeError, ValueError):
            continue  # '.' = missing
        d = pd.Timestamp(o["date"], tz="UTC")
        if vintages and o.get("realtime_start"):
            pub = pd.Timestamp(o["realtime_start"], tz="UTC") + pd.Timedelta(hours=RELEASE_HOUR_UTC)
            meta = {"revision_risk": False, "publication_time": "vintage (ALFRED first release)", "source": "FRED API"}
        else:
            pub = d + spec.lag
            meta = {"revision_risk": spec.revisable, "publication_time": "approximate", "source": "FRED API"}
        out.append({"observed_at": d.isoformat(), "published_at": pub.to_pydatetime().isoformat(),
                    "fetched_at": fetched_at.isoformat(), "value": v, "meta": meta})
    return out


class FredSource:
    def __init__(self, http: HttpClient | None = None, api_key: str | None = None):
        import os
        self.http = http or HttpClient(limiter=RateLimiter(calls=20, period=60.0))
        self.api_key = api_key if api_key is not None else os.environ.get("FRED_API_KEY", "").strip()
        self.last_error: str | None = None
        self.last_source: str | None = None  # "FRED API" or "fredgraph.csv" — recorded with every fetch

    def fetch(self, series: str, start: str = "2015-01-01") -> list[dict]:
        spec = SERIES[series]
        try:
            if self.api_key:
                q = {"series_id": series, "api_key": self.api_key, "file_type": "json", "observation_start": start}
                if spec.revisable:
                    q.update(output_type="4", realtime_start="1776-07-04", realtime_end="9999-12-31")
                r = self.http.get(API_URL, q)
                self.last_source = "FRED API"
                return parse_api_json(r.text, spec, datetime.now(timezone.utc), vintages=spec.revisable)
            # fallback without a key (FRED's terms ask for the API: documented, used only in the experimental phase)
            r = self.http.get(URL, {"id": series, "cosd": start})
            self.last_source = "fredgraph.csv"
            return parse_fredgraph_csv(r.text, spec, datetime.now(timezone.utc))
        except (HttpError, ValueError) as exc:
            self.last_error = str(exc)
            raise
