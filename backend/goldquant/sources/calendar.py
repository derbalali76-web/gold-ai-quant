"""Economic calendar loaded from a user-maintained JSON file (data/calendar.json).

No free, legally redistributable consensus/actual feed was verified (P0), so the calendar is a local file the
user fills from official release schedules (BLS, BEA, Fed). Consensus is optional; without it the
Expectation Gap / Priced-In engines stay disabled. The calendar counts as "connected" only if it was updated
within the last 8 days and lists at least one future event.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

STALE_AFTER = timedelta(days=8)


@dataclass
class CalendarEvent:
    time_utc: datetime
    name: str
    importance: int  # 1..3
    source: str
    consensus: Optional[float] = None
    actual: Optional[float] = None
    previous: Optional[float] = None
    actual_published_at: Optional[datetime] = None


@dataclass
class Calendar:
    events: list
    updated_at: Optional[datetime]

    def connected(self, now: datetime) -> bool:
        return (self.updated_at is not None and now - self.updated_at <= STALE_AFTER
                and any(e.time_utc > now for e in self.events))

    def embargo(self, now: datetime, before_min: int = 30, after_min: int = 30) -> list[CalendarEvent]:
        return [e for e in self.events if e.importance >= 3
                and -before_min * 60 <= (now - e.time_utc).total_seconds() <= after_min * 60]

    def upcoming(self, now: datetime, hours: int = 72) -> list[CalendarEvent]:
        return [e for e in self.events if e.importance >= 3 and now < e.time_utc <= now + timedelta(hours=hours)]


def _dt(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def load_calendars(paths) -> Calendar:
    """Merge several calendar files (manual + automatic). Missing files are skipped; the freshest
    `updated_at` wins; identical (time, name) events are de-duplicated."""
    events, stamps, seen = [], [], set()
    for p in paths:
        c = load_calendar(p)
        if c.updated_at is not None:
            stamps.append(c.updated_at)
        for e in c.events:
            k = (e.time_utc, e.name)
            if k not in seen:
                seen.add(k)
                events.append(e)
    return Calendar(sorted(events, key=lambda x: x.time_utc), max(stamps) if stamps else None)


def load_calendar(path: str | Path) -> Calendar:
    p = Path(path)
    if not p.exists():
        return Calendar([], None)
    o = json.loads(p.read_text(encoding="utf-8"))
    ev = []
    for e in o.get("events", []):
        imp = int(e.get("importance", 1))
        if imp not in (1, 2, 3):
            raise ValueError(f"bad importance in {e}")
        ev.append(CalendarEvent(_dt(e["time_utc"]), str(e["name"]), imp, str(e.get("source", "user")),
                                e.get("consensus"), e.get("actual"), e.get("previous"), _dt(e.get("actual_published_at"))))
    return Calendar(sorted(ev, key=lambda x: x.time_utc), _dt(o.get("updated_at")))
