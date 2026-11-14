"""Point-in-time recorder of economic-calendar FORECASTS (free weekly feed, no key).

What moves gold at a release is the SURPRISE (actual - consensus forecast), and consensus history is not
available for free. So we build our own: every collect run stores the week's USD high/medium-impact events with
the forecast as it was published at that moment (first-seen time), appending a new line only when a value changes.
Actual values come later (from the feed if it carries them, otherwise from FRED for the mapped series).
Nothing here is used by the models until months of history exist and the surprise feature passes the research gate.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..providers.http import HttpClient, RateLimiter

URLS = ("https://nfs.faireconomy.media/ff_calendar_thisweek.json",)
KEEP_IMPACT = {"High", "Medium"}
FIELDS = ("forecast", "previous", "actual")


def _key(e: dict) -> str:
    return f"{e.get('date', '')}|{e.get('title', '')}"


def parse(payload: list) -> list[dict]:
    out = []
    for e in payload or []:
        if not isinstance(e, dict) or e.get("country") != "USD" or e.get("impact") not in KEEP_IMPACT:
            continue
        out.append({"key": _key(e), "title": str(e.get("title", ""))[:120], "time": str(e.get("date", "")),
                    "impact": e.get("impact"), **{f: (str(e[f]) if e.get(f) not in (None, "") else None) for f in FIELDS}})
    return out


def record(events: list[dict], path: Path, seen_at: datetime) -> int:
    """Append events that are new or whose forecast / previous / actual changed. Returns lines added."""
    path.parent.mkdir(parents=True, exist_ok=True)
    last: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                last[r["key"]] = r
    added = []
    for e in events:
        prev = last.get(e["key"])
        if prev is not None and all(prev.get(f) == e.get(f) for f in FIELDS):
            continue
        r = dict(e, seen_at=seen_at.isoformat())
        added.append(r)
        last[e["key"]] = r
    if added:
        with path.open("a", encoding="utf-8") as f:
            for r in added:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    return len(added)


def refresh(path: Path, now: datetime, http: HttpClient | None = None) -> str:
    http = http or HttpClient(limiter=RateLimiter(calls=2, period=60.0), retries=2)
    for url in URLS:
        try:
            r = http.get(url)
            return f"{record(parse(json.loads(r.text)), path, now)} new lines"
        except Exception as exc:  # noqa: BLE001 — informational; never blocks collection
            err = str(exc)
    return f"failed: {err[:120]}"
