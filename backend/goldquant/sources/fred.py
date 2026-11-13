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


class FredSource:
    def __init__(self, http: HttpClient | None = None):
        self.http = http or HttpClient(limiter=RateLimiter(calls=20, period=60.0))
        self.last_error: str | None = None

    def fetch(self, series: str, start: str = "2015-01-01") -> list[dict]:
        spec = SERIES[series]
        try:
            r = self.http.get(URL, {"id": series, "cosd": start})
            return parse_fredgraph_csv(r.text, spec, datetime.now(timezone.utc))
        except (HttpError, ValueError) as exc:
            self.last_error = str(exc)
            raise
