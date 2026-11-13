"""Automatic economic calendar from OFFICIAL US sources (no key, free):

* BLS iCalendar feed (Employment Situation / NFP, CPI, PPI, JOLTS, ECI...) — times are US Eastern.
* Federal Reserve FOMC meeting calendar page — policy statement at 14:00 US Eastern on the last meeting day.
  A built-in list of already-published decision dates is kept as a fallback if the page layout changes.

The CI job (tools/cloud_job.py collect) refreshes models/calendar_auto.json; the server merges it with the
user's manual config/calendar.json. If every source fails, the previous file is kept unchanged, so its
`updated_at` ages and after 8 days the calendar counts as disconnected -> live hourly signals stop (safe).
Release TIMES come from the schedules; consensus/actual values are NOT available here (never invented).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..providers.http import HttpClient, HttpError, RateLimiter

ET = ZoneInfo("America/New_York")
BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

# (pattern in the BLS title, importance, short English name)
BLS_RULES = [
    (r"employment situation(?! of)", 3, "US Nonfarm Payrolls (Employment Situation)"),
    (r"^consumer price index", 3, "US CPI"),
    (r"^producer price index", 2, "US PPI"),
    (r"job openings and labor turnover", 2, "US JOLTS"),
    (r"employment cost index", 2, "US Employment Cost Index"),
    (r"productivity and costs", 1, "US Productivity and Costs"),
]
# decision days already published by the Federal Reserve (fallback only; the live page takes precedence)
FOMC_FALLBACK = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16",
                 "2026-10-28", "2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28"]
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def _unfold(text: str) -> list[str]:
    out: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _ics_time(prop: str, value: str) -> datetime | None:
    if "VALUE=DATE" in prop.upper() and "T" not in value:
        return None  # all-day entries (holidays) carry no release time
    v = value.strip()
    if v.endswith("Z"):
        return datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    dt = datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
    return dt.replace(tzinfo=ET).astimezone(timezone.utc)  # BLS: TZID US-Eastern or floating Eastern time


def parse_bls_ics(text: str) -> list[dict]:
    if "BEGIN:VCALENDAR" not in text:
        raise ValueError("not an iCalendar payload")
    events, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            title, start = cur.get("summary", ""), cur.get("start")
            for pat, imp, name in BLS_RULES:
                if start and re.search(pat, title.strip(), re.I):
                    events.append({"time_utc": start.isoformat().replace("+00:00", "Z"), "name": name,
                                   "importance": imp, "source": "bls.gov", "detail": title.strip()[:120]})
                    break
            cur = None
        elif cur is not None and ":" in line:
            prop, val = line.split(":", 1)
            key = prop.split(";")[0].upper()
            if key == "SUMMARY":
                cur["summary"] = val.replace("\\,", ",").replace("\\;", ";")
            elif key == "DTSTART":
                cur["start"] = _ics_time(prop, val)
    return events


def _fomc_event(d: date) -> dict:
    t = datetime(d.year, d.month, d.day, 14, 0, tzinfo=ET).astimezone(timezone.utc)
    return {"time_utc": t.isoformat().replace("+00:00", "Z"), "name": "FOMC rate decision", "importance": 3,
            "source": "federalreserve.gov"}


def parse_fomc_html(html: str) -> list[dict]:
    """Year sections '<year> FOMC Meetings' -> (month, 'dd-dd' or 'dd') pairs; last day = decision day."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    events = []
    parts = re.split(r"((?:19|20)\d\d) FOMC Meetings", text)
    for i in range(1, len(parts) - 1, 2):
        year, body = int(parts[i]), parts[i + 1]
        for m in re.finditer(r"\b(January|February|March|April|May|June|July|August|September|October|November|"
                             r"December)(?:/(January|February|March|April|May|June|July|August|September|October|"
                             r"November|December))?\s+(\d{1,2})(?:-(\d{1,2}))?\*?", body):
            month = MONTHS[(m.group(2) or m.group(1)).lower()]
            day = int(m.group(4) or m.group(3))
            try:
                events.append(_fomc_event(date(year, month, day)))
            except ValueError:
                continue
    if not events:
        raise ValueError("no FOMC meetings found on the page (layout changed?)")
    return events


def build(now: datetime, http: HttpClient | None = None) -> dict:
    http = http or HttpClient(limiter=RateLimiter(calls=4, period=10.0))
    events, status = [], {}
    try:
        events += parse_bls_ics(http.get(BLS_ICS).text)
        status["bls"] = "ok"
    except (HttpError, ValueError) as exc:
        status["bls"] = f"error: {str(exc)[:120]}"
    try:
        events += parse_fomc_html(http.get(FOMC_URL).text)
        status["fomc"] = "ok"
    except (HttpError, ValueError) as exc:
        status["fomc"] = f"fallback list (page error: {str(exc)[:100]})"
        events += [_fomc_event(date.fromisoformat(d)) for d in FOMC_FALLBACK]
    lo, hi = now - timedelta(days=2), now + timedelta(days=120)
    seen, keep = set(), []
    for e in sorted(events, key=lambda x: x["time_utc"]):
        t = datetime.fromisoformat(e["time_utc"].replace("Z", "+00:00"))
        k = (e["time_utc"], e["name"])
        if lo <= t <= hi and k not in seen:
            seen.add(k)
            keep.append(e)
    ok = any(v == "ok" for v in status.values())
    return {"updated_at": now.isoformat().replace("+00:00", "Z") if ok else None, "sources": status, "events": keep,
            "_comment": "ملف مولّد تلقائياً من bls.gov و federalreserve.gov — لا تعدّله يدوياً؛ أضف أحداثك في config/calendar.json"}


def refresh(path: Path, now: datetime, http: HttpClient | None = None) -> dict:
    """Write a new file only if at least one OFFICIAL source answered; otherwise keep the old one."""
    new = build(now, http)
    if path.exists():  # a source that failed this time keeps its previous events (no silent loss of NFP/CPI)
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
        src_of = {"bls": "bls.gov", "fomc": "federalreserve.gov"}
        lo = now - timedelta(days=2)
        for key, src in src_of.items():
            if new["sources"].get(key) != "ok":
                carried = [e for e in old.get("events", []) if e.get("source") == src
                           and datetime.fromisoformat(e["time_utc"].replace("Z", "+00:00")) >= lo]
                if carried:
                    new["events"] = [e for e in new["events"] if e.get("source") != src] + carried
                    new["sources"][key] += " — kept previous events"
        new["events"].sort(key=lambda x: x["time_utc"])
    if new["updated_at"] is None:
        return {"written": False, "sources": new["sources"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"written": True, "sources": new["sources"], "events": len(new["events"])}
