"""Non-price context (macro, COT, news, calendar) gathered with TTL caching and point-in-time filtering.

Every source can fail independently; failures are recorded and surface as `missing_data`, never as guesses.
"""
from __future__ import annotations

import logging

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


CAL_CONNECTED, CAL_NO_EVENTS, CAL_STALE, CAL_DISCONNECTED, CAL_NOT_CONFIGURED = (
    "CONNECTED", "NO_EVENTS", "STALE", "DISCONNECTED", "NOT_CONFIGURED")
log = logging.getLogger("goldquant.calendar")


@dataclass
class MarketContext:
    calendar_connected: bool = False
    calendar_state: str = CAL_NOT_CONFIGURED
    calendar_updated_at: Optional[str] = None  # last successful refresh of the calendar file(s)
    calendar_reason: Optional[str] = None
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

    def calendar_status(self, as_of: datetime) -> dict:
        """Calendar state without guessing: NOT_CONFIGURED (no file), DISCONNECTED (unreadable), STALE (older than
        8 days or no future event), CONNECTED / NO_EVENTS (fresh; NO_EVENTS = nothing high-impact in 24 h).
        Files are re-read only when they change (mtime cache); the reason is logged, never any key."""
        paths = [self.calendar_path] + ([self.auto_calendar_path] if self.auto_calendar_path else [])
        existing = [p for p in paths if p.exists()]
        key = tuple((str(p), p.stat().st_mtime) for p in existing)
        cached = getattr(self, "_cal_cache", None)
        if cached and cached[0] == key:
            cal, err = cached[1], cached[2]
        else:
            cal, err = None, None
            if existing:
                try:
                    cal = CAL.load_calendars(existing)
                except (ValueError, KeyError, OSError) as exc:
                    err = f"calendar file unreadable: {type(exc).__name__}: {str(exc)[:120]}"
            self._cal_cache = (key, cal, err)
        st = {"state": CAL_NOT_CONFIGURED, "updated_at": None, "reason": "no calendar file", "cal": cal}
        if not existing:
            pass
        elif cal is None:
            st.update(state=CAL_DISCONNECTED, reason=err)
        else:
            st["updated_at"] = cal.updated_at.isoformat() if cal.updated_at else None
            if cal.connected(as_of):
                soon = cal.upcoming(as_of, hours=24)
                st.update(state=CAL_CONNECTED if soon else CAL_NO_EVENTS, reason=None)
            else:
                age = (as_of - cal.updated_at) if cal.updated_at else None
                st.update(state=CAL_STALE, reason=("no future event listed" if age is not None and age <= CAL.STALE_AFTER
                                                   else f"last successful update {st['updated_at']}"))
        if st["state"] not in (CAL_CONNECTED, CAL_NO_EVENTS):
            prev = getattr(self, "_cal_logged", None)
            if prev != (st["state"], st["reason"]):
                log.warning("economic calendar %s: %s", st["state"], st["reason"])
                self._cal_logged = (st["state"], st["reason"])
        return st

    def snapshot(self, as_of: datetime) -> MarketContext:
        ctx = MarketContext()
        cs = self.calendar_status(as_of)
        cal = cs.pop("cal")
        ctx.calendar_state, ctx.calendar_updated_at, ctx.calendar_reason = cs["state"], cs["updated_at"], cs["reason"]
        ctx.calendar_connected = cs["state"] in (CAL_CONNECTED, CAL_NO_EVENTS)
        if cs["state"] == CAL_DISCONNECTED:
            ctx.missing.append(f"ملف التقويم غير صالح: {cs['reason']}")
        if cal is not None and ctx.calendar_connected:
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


def news_clear(ctx) -> bool:
    """True ONLY when the calendar is verified (fresh) AND no high-impact event is in the embargo window.
    An unknown calendar is never 'no news': any trading engine (scalping included) must treat it as not clear."""
    return bool(ctx is not None and getattr(ctx, "calendar_connected", False)
                and getattr(ctx, "calendar_state", None) in (CAL_CONNECTED, CAL_NO_EVENTS)
                and not getattr(ctx, "embargo_events", None))
