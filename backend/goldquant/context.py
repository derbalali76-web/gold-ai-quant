"""Non-price context (macro, COT, news, calendar) gathered with TTL caching and point-in-time filtering.

Every source can fail independently; failures are recorded and surface as `missing_data`, never as guesses.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from .providers.history import HistoryStore
from .sources import calendar as CAL
from .sources.cftc import CftcSource, footprint_as_of
from .sources.etf import EtfSource, flows_as_of
from .sources.fred import FredSource
from .sources.news import NewsSource, cluster, recent_high_impact

MACRO_SERIES = ("DFII10", "DGS10", "DTWEXBGS", "GVZCLS")


@dataclass
class MarketContext:
    calendar_connected: bool = False
    embargo_events: list = field(default_factory=list)  # names of high-impact events within ±30 min
    recent_news: list = field(default_factory=list)  # (source, title, published_at) high-impact last 30 min
    footprint: Optional[dict] = None
    etf_flows: Optional[dict] = None
    macro: dict = field(default_factory=dict)  # series -> {value, change_5d, observed_at, published_at}
    missing: list = field(default_factory=list)
    sources_status: dict = field(default_factory=dict)


class ContextService:
    def __init__(self, history: HistoryStore, calendar_path: str | Path, fred: FredSource | None = None,
                 cftc: CftcSource | None = None, news: NewsSource | None = None, enabled: bool = True,
                 etf: EtfSource | None = None):
        self.history, self.calendar_path = history, Path(calendar_path)
        self.fred, self.cftc, self.news = fred or FredSource(), cftc or CftcSource(), news or NewsSource()
        self.etf = etf or EtfSource()
        self.enabled = enabled
        self._next: dict[str, datetime] = {}
        self._cot: Optional[pd.DataFrame] = None
        self._news_items: list = []
        self._lock = threading.Lock()

    def _due(self, key: str, now: datetime, ttl: timedelta) -> bool:
        if self._next.get(key) and now < self._next[key]:
            return False
        self._next[key] = now + ttl
        return True

    def refresh(self, now: datetime) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._due("fred", now, timedelta(hours=6)):
                for s in MACRO_SERIES:
                    try:
                        self.history.upsert_observations("FRED", s, self.fred.fetch(s, start="2018-01-01"))
                        self.history.log_fetch(now, f"FRED:{s}", True, self.fred.http.last_latency_ms, "ok")
                    except Exception as exc:  # noqa: BLE001 — recorded, never fatal
                        self.history.log_fetch(now, f"FRED:{s}", False, None, str(exc))
            if self._due("cftc", now, timedelta(hours=12)):
                try:
                    self._cot = self.cftc.fetch()
                    self.history.log_fetch(now, "CFTC", True, self.cftc.http.last_latency_ms, f"{len(self._cot)} weeks")
                except Exception as exc:  # noqa: BLE001
                    self.history.log_fetch(now, "CFTC", False, None, str(exc))
            if self._due("etf", now, timedelta(hours=12)):
                try:
                    self.history.upsert_observations("SPDR", "GLD_TONNES", self.etf.fetch())
                    self.history.log_fetch(now, "SPDR:GLD", True, None, "ok")
                except Exception as exc:  # noqa: BLE001
                    self.history.log_fetch(now, "SPDR:GLD", False, None, str(exc))
            if self._due("news", now, timedelta(minutes=5)):
                items = self.news.fetch_all()
                if items:
                    self._news_items = items
                self.history.log_fetch(now, "RSS", bool(items), None, f"{len(items)} items; errors={list(self.news.errors)}")

    def snapshot(self, as_of: datetime) -> MarketContext:
        ctx = MarketContext()
        cal = None
        try:
            cal = CAL.load_calendar(self.calendar_path)
        except (ValueError, KeyError) as exc:
            ctx.missing.append(f"ملف التقويم غير صالح: {exc}")
        if cal is not None:
            ctx.calendar_connected = cal.connected(as_of)
            ctx.embargo_events = [e.name for e in cal.embargo(as_of)]
        if not ctx.calendar_connected:
            ctx.missing.append("تقويم الأحداث الاقتصادية غير محدّث (data/calendar.json)")
        for s in MACRO_SERIES:
            df = self.history.load_observations_as_of("FRED", s, as_of)
            if df.empty:
                ctx.missing.append(f"FRED {s} غير متاح")
                continue
            last = df.iloc[-1]
            prev = df.iloc[-6] if len(df) > 5 else df.iloc[0]
            ctx.macro[s] = {"value": float(last["value"]), "change_5obs": float(last["value"] - prev["value"]),
                            "observed_at": last["observed_at"], "published_at": last["published_at"]}
        gld = self.history.load_observations_as_of("SPDR", "GLD_TONNES", as_of)
        ctx.etf_flows = flows_as_of(gld) if len(gld) else None
        if ctx.etf_flows is None:
            ctx.missing.append("حيازات صندوق GLD غير متاحة")
        if self._cot is not None:
            ctx.footprint = footprint_as_of(self._cot, as_of)
        if ctx.footprint is None:
            ctx.missing.append("بيانات CFTC COT غير متاحة")
        if self._news_items:
            from .reliability.firewall import check_news
            kept, warns = check_news(self._news_items, as_of)
            ctx.missing.extend(warns)
            ctx.recent_news = [(i.source, i.title, i.published_at.isoformat())
                               for i in recent_high_impact(cluster(kept), as_of)]
        else:
            ctx.missing.append("خلاصات الأخبار الرسمية (RSS) غير متاحة")
        ctx.sources_status = {"news_errors": dict(self.news.errors), "fred_error": self.fred.last_error,
                              "cftc_error": self.cftc.last_error}
        return ctx
