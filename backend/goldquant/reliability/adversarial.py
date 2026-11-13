"""Adversarial Market Testing (V4 #9): hostile scenarios applied to a real provider; the engine must never
answer BUY/SELL in any of them (expected: UNAVAILABLE or WAIT)."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from ..providers.base import Bars, MarketDataProvider


class Scenario(MarketDataProvider):
    def __init__(self, base: MarketDataProvider, name: str):
        self.base, self.name, self.meta = base, name, base.meta

    def quote(self, as_of):
        q = self.base.quote(as_of)
        if q is None:
            return q
        if self.name == "stale_feed":
            q.observed_at -= timedelta(minutes=30)
        elif self.name == "clock_skew_future":
            q.observed_at += timedelta(minutes=10)
        elif self.name == "source_conflict":
            q.warnings.append("تعارض بين مصدري السعر (5.00%) — البيانات مشكوك فيها")
        elif self.name == "flash_crash_quote":
            q.price = round(q.price * 0.95, 2)
        return q

    def bars(self, tf, as_of, count):
        b = self.base.bars(tf, as_of, count)
        if b is None or tf != "M15":
            return b
        df = b.df.copy()
        if self.name == "frozen_feed":
            df.iloc[-10:, :4] = float(df["close"].iloc[-11])
        elif self.name == "bad_tick":
            i = df.columns.get_loc("close")
            df.iloc[-4, i] *= 1.06
            df.iloc[-4, df.columns.get_loc("high")] = max(df.iloc[-4]["high"], df.iloc[-4, i])
        elif self.name == "feed_gap":
            df = df.iloc[:-12]
        elif self.name == "flash_crash_bar":
            px = df.iloc[-2]["close"]
            df.iloc[-2, df.columns.get_loc("low")] = px * 0.93
        return Bars(tf, df, b.provider, b.fetched_at)


SCENARIOS = ["stale_feed", "clock_skew_future", "source_conflict", "flash_crash_quote", "frozen_feed", "bad_tick",
             "feed_gap", "flash_crash_bar"]


def run_all(engine, base: MarketDataProvider, mode, as_of) -> list[dict]:
    out = []
    for name in SCENARIOS:
        d = engine.decide(Scenario(base, name), mode, as_of)
        out.append({"scenario": name, "action": d.action.value, "reason": d.warning_ar or d.reason_short_ar,
                    "safe": d.action.value in ("WAIT", "UNAVAILABLE")})
    return out
