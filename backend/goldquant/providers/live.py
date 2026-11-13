"""Composite LIVE provider: Twelve Data primary + xaus.com independent quote cross-check."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .base import Bars, MarketDataProvider, ProviderMeta, Quote
from .twelvedata import TwelveDataProvider
from .xaus import XausSpot

MAX_DISAGREEMENT = 0.003  # 0.3 %
MAX_CHECK_AGE_S = 300


class LiveProvider(MarketDataProvider):
    def __init__(self, primary: TwelveDataProvider, checker: XausSpot | None = None):
        self.primary = primary
        self.checker = checker
        self.meta = ProviderMeta(**{**primary.meta.__dict__, "name": primary.meta.name})
        self.last_cross_check: dict = {}

    def quote(self, as_of: datetime) -> Optional[Quote]:
        q = self.primary.quote(as_of)
        if q is None or self.checker is None:
            return q
        c = self.checker.quote()
        if c is None:
            q.warnings.append("تعذّر التحقق المتقاطع من السعر (xaus.com)")
            self.last_cross_check = {"ok": False, "error": self.checker.last_error}
            return q
        diff = abs(c.price - q.price) / q.price
        age = abs((c.observed_at - q.observed_at).total_seconds())
        self.last_cross_check = {"ok": True, "other": c.price, "rel_diff": round(diff, 5), "time_gap_s": age}
        if age <= MAX_CHECK_AGE_S and diff > MAX_DISAGREEMENT:
            q.warnings.append(f"تعارض بين مصدري السعر ({diff:.2%}) — البيانات مشكوك فيها")
        return q

    def bars(self, timeframe: str, as_of: datetime, count: int) -> Optional[Bars]:
        return self.primary.bars(timeframe, as_of, count)
