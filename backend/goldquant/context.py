"""Non-price context (macro, COT, news, calendar) gathered with TTL caching and point-in-time filtering.

Every source can fail independently; failures are recorded and surface as `missing_data`, never as guesses.
"""
from __future__ import annotations

from .msg import M

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
EMBARGO_BEFORE_MIN = 60  # top-tier releases (NFP, CPI, FOMC...) move gold most in the hour around them
EMBARGO_AFTER_MIN = 45


@dataclass
class MarketContext:
    calendar_connected: bool = False
    embargo_events: list = field(default_factory=list)  # high-impact events from 60 min before to 45 min after
    upcoming_events: list = field(default_factory=list)  # high-impact events in the next 72 hours (names + time)
    recent_news: list = field(default_factory=list)  # (source, title, published_at) high-impact last 30 min
    footprint: Optional[dict] = None
    etf_flows: Optional[dict] = None
    macro: dict = field(default_factory=dict)  # series -> {value, change_5d, observed_at, published_at}
    macro_frames: dict = field(default_factory=dict)  # series -> point-in-time observations (planner features)
    missing: list = field(default_factory=list)
    sources_status: dict = field(default_factory=dict)


class ContextService:
    def __init__(self, history: HistoryStore, calendar_path: str | Path, fred: FredSource | None = None,
                 cftc: CftcSource | None = None, news: NewsSource | None = None, enabled: bool = True,
                 etf: EtfSource | None = None, auto_calendar_path: str | Path | None = None):
        self.history, self.calendar_path = history, Path(calendar_path)
        self.auto_calendar_path = Path(auto_calendar_path) if auto_calendar_path else None
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
            cal = CAL.load_calendars([self.calendar_path] + ([self.auto_calendar_path] if self.auto_calendar_path else []))
        except (ValueError, KeyError) as exc:
            ctx.missing.append(f"ملف التقويم غير صالح: {exc}")
        if cal is not None:
            ctx.calendar_connected = cal.connected(as_of)
            ctx.embargo_events = [e.name for e in cal.embargo(as_of, before_min=EMBARGO_BEFORE_MIN, after_min=EMBARGO_AFTER_MIN)]
            ctx.upcoming_events = [f"{e.name} ({e.time_utc:%Y-%m-%d %H:%M} UTC)" for e in cal.upcoming(as_of, hours=72)]
        if not ctx.calendar_connected:
            ctx.missing.append(M("md.calendar_stale"))
        for s in MACRO_SERIES:
            df = self.history.load_observations_as_of("FRED", s, as_of)
            if df.empty:
                ctx.missing.append(M("md.fred", s))
                continue
            ctx.macro_frames[s] = df
            last = df.iloc[-1]
            prev = df.iloc[-6] if len(df) > 5 else df.iloc[0]
            ctx.macro[s] = {"value": float(last["value"]), "change_5obs": float(last["value"] - prev["value"]),
                            "observed_at": last["observed_at"], "published_at": last["published_at"]}
        gld = self.history.load_observations_as_of("SPDR", "GLD_TONNES", as_of)
        ctx.etf_flows = flows_as_of(gld) if len(gld) else None
        if ctx.etf_flows is None:
            ctx.missing.append(M("md.gld"))
        if self._cot is not None:
            ctx.footprint = footprint_as_of(self._cot, as_of)
        if ctx.footprint is None:
            ctx.missing.append(M("md.cftc"))
        if self._news_items:
            from .reliability.firewall import check_news
            kept, warns = check_news(self._news_items, as_of)
            ctx.missing.extend(warns)
            ctx.recent_news = [(i.source, i.title, i.published_at.isoformat())
                               for i in recent_high_impact(cluster(kept), as_of)]
        else:
            ctx.missing.append(M("md.rss"))
        ctx.sources_status = {"news_errors": dict(self.news.errors), "fred_error": self.fred.last_error,
                              "cftc_error": self.cftc.last_error}
        return ctx
