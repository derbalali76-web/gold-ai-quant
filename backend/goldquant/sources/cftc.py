"""CFTC Commitments of Traders — Disaggregated Futures-Only, COMEX gold (contract code 088691).

Public Socrata API, weekly. Positions are as of Tuesday and released Friday 15:30 US/Eastern, so every row gets
published_at = report date + 3 days 20:30 UTC (conservative; covers EST and EDT). Features must use published_at.
Field names follow the public dataset; parsed defensively and verified by the live contract check.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ..providers.http import HttpClient, HttpError, RateLimiter

URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
GOLD_CODE = "088691"


def parse_cot(text: str, fetched_at: datetime) -> pd.DataFrame:
    rows = json.loads(text)
    if not isinstance(rows, list):
        raise ValueError("unexpected COT payload")
    recs = []
    for r in rows:
        d = pd.Timestamp(r["report_date_as_yyyy_mm_dd"])
        d = (d.tz_localize("UTC") if d.tzinfo is None else d.tz_convert("UTC")).normalize()
        mm_long = float(r["m_money_positions_long_all"])
        mm_short = float(r["m_money_positions_short_all"])
        oi = float(r["open_interest_all"])
        recs.append({"observed_at": d, "published_at": d + timedelta(days=3, hours=20, minutes=30),
                     "fetched_at": fetched_at, "mm_net": mm_long - mm_short, "open_interest": oi,
                     "mm_net_pct_oi": (mm_long - mm_short) / oi if oi else np.nan})
    return pd.DataFrame(recs).sort_values("observed_at").reset_index(drop=True)


def footprint_as_of(cot: pd.DataFrame, as_of: datetime, lookback_weeks: int = 156) -> dict | None:
    """Institutional Footprint (V2 #4): managed-money positioning percentile & weekly change, as of a time."""
    usable = cot[cot["published_at"] <= pd.Timestamp(as_of)]
    if len(usable) < 26:
        return None
    hist = usable.tail(lookback_weeks)
    last = hist.iloc[-1]
    pct = float((hist["mm_net_pct_oi"] <= last["mm_net_pct_oi"]).mean())
    chg = float(last["mm_net"] - hist.iloc[-2]["mm_net"]) if len(hist) > 1 else 0.0
    return {"report_date": last["observed_at"].date().isoformat(), "published_at": last["published_at"].isoformat(),
            "mm_net": float(last["mm_net"]), "mm_net_pct_oi": round(float(last["mm_net_pct_oi"]), 4),
            "percentile_3y": round(pct, 3), "weekly_change": chg,
            "crowded": "LONG" if pct >= 0.9 else ("SHORT" if pct <= 0.1 else None),
            "age_days": round((pd.Timestamp(as_of) - last["observed_at"]).total_seconds() / 86400, 1)}


class CftcSource:
    def __init__(self, http: HttpClient | None = None):
        self.http = http or HttpClient(limiter=RateLimiter(calls=10, period=60.0))
        self.last_error: str | None = None

    def fetch(self, weeks: int = 260) -> pd.DataFrame:
        params = {"cftc_contract_market_code": GOLD_CODE, "$order": "report_date_as_yyyy_mm_dd DESC",
                  "$limit": weeks}
        try:
            r = self.http.get(URL, params)
            return parse_cot(r.text, datetime.now(timezone.utc))
        except (HttpError, ValueError, KeyError) as exc:
            self.last_error = str(exc)
            raise
