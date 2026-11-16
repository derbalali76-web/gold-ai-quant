#!/usr/bin/env python3
"""Hourly health check of the AI QUANT server, run by the public ledger workflow (standard library only).

Writes monitor.json (current status per asset) and prints ALERT lines; the workflow opens one GitHub issue
"AI QUANT alert" while something is wrong (the repository owner gets it by e-mail) and closes it when all is well.
Checks per asset: snapshot reachable (alerted when unreachable in two runs in a row), analysis fresh (gold: only while the market is open), data-quality gate.
Record checks (since 2026-11-16): an issue time of the live high / low validation or of a price range missed in the
last 24 h (it can never be recorded later), a problem of the independent issuer (issue.py), or a disagreement between
the issuer and the server on the same issue (crosscheck.json).

usage: monitor.py [--issuer ISSUER_LOG] SNAPSHOT.json ...
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


def record_checks(root: Path, issuer_log: str | None) -> list[str]:
    out = []
    try:
        comp = json.loads((root / "stats.json").read_text(encoding="utf-8")).get("completeness", {}).get("cases", {})
    except Exception:  # noqa: BLE001
        comp = {}
    for case, c in comp.items():
        if c.get("missed_24h"):
            why = " (gold: a market holiday also counts)" if " XAU " in case else ""
            out.append(f"record: {case} missed {c['missed_24h']} issue time(s) in the last 24 h{why}; "
                       f"completeness {c.get('recorded')}/{c.get('expected')}")
    if issuer_log and Path(issuer_log).exists():
        for ln in Path(issuer_log).read_text(encoding="utf-8").splitlines():
            if ln.startswith("ISSUER-PROBLEM"):
                out.append("independent issuer: " + ln[len("ISSUER-PROBLEM "):][:200])
    try:
        checks = json.loads((root / "crosscheck.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        checks = []
    now = datetime.now(timezone.utc)
    run = [c for c in checks if c.get("run") and now - datetime.fromisoformat(c["run"].replace("Z", "+00:00"))
           < timedelta(minutes=30)]  # this run only: an old disagreement is in the file, not a new alert
    for c in run:
        if not c.get("agree"):
            out.append(f"record: server and independent issuer disagree on {c['kind']} {c['asset']} {c['horizon']} "
                       f"{c['issued_at']} by {c['max_rel_diff'] * 100:.3f} % (the first recorded value stands)")
    return out


def main(argv: list[str]) -> int:
    issuer_log = None
    if argv[:1] == ["--issuer"]:
        issuer_log, argv = argv[1], argv[2:]
    files = argv
    now = datetime.now(timezone.utc)
    status, alerts = {}, []
    root = Path(__file__).resolve().parent
    try:  # the previous run's status: one slow answer from the free server is not an outage
        before = json.loads((root / "monitor.json").read_text(encoding="utf-8")).get("assets", {})
    except Exception:  # noqa: BLE001
        before = {}
    for f in files:
        asset = Path(f).stem.split("_")[-1]
        try:
            snap = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            snap = {}
        a = check(asset, snap, now)
        status[asset] = {"ok": not a, "problems": a, "as_of": snap.get("as_of"), "health": snap.get("health")}
        prev = (before.get(asset) or {}).get("problems") or []
        alerts += [x for x in a if "unreachable" not in x or x in prev]  # unreachable twice in a row -> alert
    rec = record_checks(root, issuer_log)
    alerts += rec
    (root / "monitor.json").write_text(json.dumps({"checked_at": now.isoformat(timespec="seconds"),
                                                   "assets": status, "record": rec}, indent=1), encoding="utf-8")
    for a in alerts:
        print("ALERT", a)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
