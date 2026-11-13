"""xaus.com free spot endpoint (no key). Used ONLY as an independent cross-check of the primary quote.

Daily history from this source is not used for intraday modelling. verified=False until the live contract
check passes on the user's machine (response field names are taken from the public docs and parsed defensively).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import pandas as pd

from .base import ProviderMeta, Quote, utcnow
from .http import HttpClient, HttpError, RateLimiter

URL = "https://xaus.com/api/v1/spot"


def parse_spot(text: str, fetched_at: datetime) -> Quote:
    o = json.loads(text)
    price = o.get("spot_usd_oz")
    if price is None and isinstance(o.get("xau"), dict):
        price = o["xau"].get("price")
    ts = o.get("updated_at") or (o.get("xau") or {}).get("updated_at")
    if price is None or ts is None:
        raise ValueError("missing price or updated_at")
    return Quote(price=round(float(price), 2), observed_at=pd.Timestamp(ts).tz_convert("UTC").to_pydatetime(),
                 fetched_at=fetched_at, provider="xaus.com")


class XausSpot:
    meta = ProviderMeta(name="xaus.com", license_note="Free public API; attribution to xaus.com", cost="FREE",
                        update_interval_seconds=30, timezone="UTC", spot_or_proxy="SPOT", requires_key=False,
                        verified=False, limits_note="cached 30s at edge; cross-check only")

    def __init__(self, http: HttpClient | None = None, clock=utcnow):
        self.http = http or HttpClient(limiter=RateLimiter(calls=30, period=60.0), retries=1)
        self.clock = clock
        self.last_error: Optional[str] = None

    def quote(self) -> Optional[Quote]:
        try:
            r = self.http.get(URL, {"currency": "USD", "unit": "oz"})
            return parse_spot(r.text, self.clock())
        except (HttpError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return None
