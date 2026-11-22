#!/usr/bin/env python3
"""Runs in the public ledger every hour: a durable record of the Render server's life, outside Render.

The server keeps nothing across restarts (its disk is wiped), so the evidence of restarts, sleeps and memory
pressure must live here. Reads GET /health (boot id, uptime, memory) and appends to server/health.jsonl (own hash
chain) only when something changes: a new boot id (= restart), unreachable <-> reachable, or memory above 80 % of
the free plan. server/health_state.json summarises restarts per day for the app and for diagnosis.

usage: server_watch.py fetch URL OUT_FILE     (network; in the workflow, before recording)
       server_watch.py apply IN_FILE [REPO]   (deterministic; inside record.sh, survives its retries)
       server_watch.py check URL [REPO]       (both at once, for manual use)
Exit code 0 always: the range ledger never depends on this.
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LIMIT_MB = 512.0          # Render free web service


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def lines(repo: Path) -> list:
    p = repo / "server" / "health.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def append(repo: Path, ls: list, kind: str, data: dict, now: datetime) -> None:
    prev = ls[-1]["hash"] if ls else "0" * 64
    e = {"seq": len(ls) + 1, "kind": kind, "recorded_at": iso(now), "data": data, "prev": prev}
    e["hash"] = hashlib.sha256((prev + canon({k: v for k, v in e.items() if k != "hash"})).encode()).hexdigest()
    ls.append(e)
    p = repo / "server" / "health.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fh.write(canon(e) + "\n")


def verify(repo: Path) -> bool:
    prev = "0" * 64
    for i, e in enumerate(lines(repo), 1):
        h = hashlib.sha256((prev + canon({k: v for k, v in e.items() if k != "hash"})).encode()).hexdigest()
        if e.get("seq") != i or e.get("prev") != prev or e.get("hash") != h:
            return False
        prev = e["hash"]
    return True


def fetch(url: str, tries: int = 3):
    err = None
    for i in range(tries):
        try:
            t0 = time.time()
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ai-quant-ledger"}), timeout=90) as r:
                return json.loads(r.read().decode()), round(time.time() - t0, 1), None
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
            time.sleep(5 * (i + 1))
    return None, None, err


def observe(repo: Path, health, latency, err, now: datetime) -> list:
    """Pure: decide which lines to append given the last state and this observation; returns kinds written."""
    ls = lines(repo)
    last = {}
    for e in ls:
        if e["kind"] in ("BOOT", "UP", "DOWN", "MEMORY"):
            last[e["kind"]] = e
    state = "DOWN" if (ls and ls[-1]["kind"] == "DOWN") else "UP"
    written = []
    if health is None:
        if state != "DOWN" or not ls:
            append(repo, ls, "DOWN", {"error": err}, now); written.append("DOWN")
        return written
    boot = health.get("boot") or {}
    bid = boot.get("id")
    if state == "DOWN" and ls:
        append(repo, ls, "UP", {"latency_s": latency}, now); written.append("UP")
    prev_boot = last.get("BOOT", {}).get("data", {}).get("id")
    if bid and bid != prev_boot:
        append(repo, ls, "BOOT", {"id": bid, "started_at": boot.get("started_at"), "uptime_s": boot.get("uptime_s"),
                                  "memory_mb": boot.get("memory_mb"), "previous": prev_boot, "latency_s": latency,
                                  "app_version": health.get("app_version")}, now)
        written.append("BOOT")
    mem = (boot.get("memory_mb") or {}).get("rss")
    if mem is not None and mem > 0.8 * LIMIT_MB:
        append(repo, ls, "MEMORY", {"id": bid, "rss_mb": mem, "peak_mb": (boot.get("memory_mb") or {}).get("peak")}, now)
        written.append("MEMORY")
    return written


def summary(repo: Path, now: datetime) -> dict:
    ls = lines(repo)
    boots = [e for e in ls if e["kind"] == "BOOT"]
    per_day = {}
    for e in boots[1:]:                      # the first BOOT is the start of observation, not a restart
        d = e["recorded_at"][:10]
        per_day[d] = per_day.get(d, 0) + 1
    st = {"updated_at": iso(now), "observed_since": ls[0]["recorded_at"] if ls else None, "restarts": len(boots) - 1 if boots else 0,
          "restarts_per_day": per_day, "down_events": sum(e["kind"] == "DOWN" for e in ls),
          "memory_alerts": sum(e["kind"] == "MEMORY" for e in ls), "last": ls[-1] if ls else None, "chain_ok": verify(repo)}
    (repo / "server").mkdir(exist_ok=True)
    (repo / "server" / "health_state.json").write_text(json.dumps(st, indent=1) + "\n")
    return st


def base(url: str) -> str:
    """Server root from either the root URL or the snapshot URL the workflow already uses."""
    return url.split("/public/")[0].rstrip("/")


def main(argv: list) -> int:
    if len(argv) >= 4 and argv[1] == "fetch":
        h, lat, err = fetch(base(argv[2]) + "/health")
        Path(argv[3]).write_text(json.dumps({"health": h, "latency_s": lat, "error": err, "at": iso(datetime.now(timezone.utc))}))
        print("server watch fetch:", "ok" if h else err)
        return 0
    if len(argv) >= 3 and argv[1] == "apply":
        repo = Path(argv[3] if len(argv) > 3 else ".")
        o = json.loads(Path(argv[2]).read_text())
        if not verify(repo):
            print("server watch: chain broken, nothing written")
            return 0
        now = datetime.fromisoformat(o["at"].replace("Z", "+00:00"))
        w = observe(repo, o["health"], o["latency_s"], o["error"], now)
        s = summary(repo, now)
        print("server watch:", w or "no change", "| restarts:", s["restarts"])
        return 0
    if len(argv) >= 3 and argv[1] == "check":
        repo = Path(argv[3] if len(argv) > 3 else ".")
        if not verify(repo):
            print("server watch: chain broken, nothing written")
            return 0
        h, lat, err = fetch(base(argv[2]) + "/health")
        now = datetime.now(timezone.utc)
        w = observe(repo, h, lat, err, now)
        s = summary(repo, now)
        print("server watch:", w or "no change", "| restarts:", s["restarts"])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
