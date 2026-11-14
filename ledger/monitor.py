#!/usr/bin/env python3
"""Hourly health check of the AI QUANT server, run by the public ledger workflow (standard library only).

Writes monitor.json (current status per asset) and prints ALERT lines; the workflow opens one GitHub issue
"AI QUANT alert" while something is wrong (the repository owner gets it by e-mail) and closes it when all is well.
Checks per asset: snapshot reachable, analysis fresh (gold: only while the market is open), data-quality gate.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def gold_open(t: datetime) -> bool:
    n = t.astimezone(NY)
    d, h = n.weekday(), n.hour
    closed = d == 5 or (d == 4 and h >= 17) or (d == 6 and h < 18) or h == 17
    return not closed


def check(asset: str, snap: dict, now: datetime) -> list[str]:
    if not snap or not snap.get("as_of"):
        return [f"{asset}: server unreachable or no snapshot"]
    out = []
    qt = snap.get("quote_time")
    market_open = asset != "XAU" or gold_open(now)
    if market_open and qt:
        age = now - datetime.fromisoformat(qt.replace("Z", "+00:00"))
        if age > timedelta(minutes=45):
            out.append(f"{asset}: price is {int(age.total_seconds() // 60)} min old")
    if snap.get("health") == "FAIL":
        out.append(f"{asset}: data-quality gate FAILED (decisions blocked)")
    if asset == "XAU" and (snap.get("app_crashes_7d") or 0) > 0:
        out.append(f"app: {snap['app_crashes_7d']} crash report(s) in the last 7 days (details: GET /crashes)")
    if market_open and snap.get("action") == "UNAVAILABLE" and asset != "XAU":
        out.append(f"{asset}: analysis unavailable")
    return out


def main(files: list[str]) -> int:
    now = datetime.now(timezone.utc)
    status, alerts = {}, []
    for f in files:
        asset = Path(f).stem.split("_")[-1]
        try:
            snap = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            snap = {}
        a = check(asset, snap, now)
        alerts += a
        status[asset] = {"ok": not a, "problems": a, "as_of": snap.get("as_of"), "health": snap.get("health")}
    root = Path(__file__).resolve().parent
    (root / "monitor.json").write_text(json.dumps({"checked_at": now.isoformat(timespec="seconds"),
                                                   "assets": status}, indent=1), encoding="utf-8")
    for a in alerts:
        print("ALERT", a)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
