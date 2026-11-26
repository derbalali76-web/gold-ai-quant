#!/usr/bin/env python3
"""lean-targets-0.1 — does «الاتجاه الحالي: صعود نحو X / هبوط نحو X» come true, and how fast?

PRE-REGISTERED 2026-11-26 (owner request), before any statement was recorded or scored. Nothing below is changed
after results exist; a new version gets a new name.

THE STATEMENT. The scenario card of each horizon writes «current trend: up toward X» when the horizon's trend is UP
(X = the nearest resistance above the price) and «down toward X» when it is DOWN (X = the nearest support below).
This file rebuilds that statement from the server's public snapshot (price, the horizon's trend, supports and
resistances). The app writes it only when no tested side is marked; that mark is not in the snapshot, so a few
recorded statements may be ones the app replaced by a tested line. That is reported here, not corrected.

WHAT IS RECORDED. Every hourly run, for each asset (XAU, BTC, ETH, SOL) and horizon (HOURS, WEEK, MONTH): a new
STATEMENT when the trend is UP or DOWN, the target exists, and that (asset, horizon) has no statement recorded in
the last 24 h. So one sample per key per day, taken whatever the price does later. Skipped: snapshot older than
2 h, market closed, trend missing or sideways. Each statement also stores the opposite level (the nearest support
for UP, the nearest resistance for DOWN). Append-only, hash-chained, never edited.

HOW IT IS SCORED, on closed H1 bars after recording, for 30 days:
  reached       the first bar whose high >= X (UP) / low <= X (DOWN); hours_to_target from recording.
  opposite      the first bar touching the opposite level; opposite_first = it came before the target
                (a bar touching both counts as opposite first).
  checkpoints   reached within 24 h, 72 h, 7 d, 30 d.
A statement is settled once reached, or after 30 days.

SUMMARY per horizon and direction (all assets together, and per asset): n, share reached within each checkpoint,
median hours to target among reached, share opposite first. Shown with its numbers only when n >= 30; below that:
INSUFFICIENT. Samples overlap in time (one per day, windows up to 30 d); that is reported, not corrected. This is a
description of what happened, not a forecast. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

VERSION = "lean-targets-0.1"
ASSETS = ("XAU", "BTC", "ETH", "SOL")
HORIZONS = ("HOURS", "WEEK", "MONTH")
BARS = {"XAU": "bars_H1.json", "BTC": "bars_BTC_H1.json", "ETH": "bars_ETH_H1.json", "SOL": "bars_SOL_H1.json"}
CHECKS = {"24h": 24, "72h": 72, "7d": 168, "30d": 720}
MAX_H = 720
EVERY = timedelta(hours=24)
STALE = timedelta(hours=2)
MIN_N = 30
FILE = Path("studies") / "lean_targets.jsonl"


def trend_code(d: Optional[str]) -> Optional[str]:
    return {"UP": "UP", "DOWN": "DOWN"}.get(d or "")


def statement(trend: Optional[str], price: float, supports: list, resistances: list) -> Optional[dict]:
    d = trend_code(trend)
    if d is None:
        return None
    above = [x for x in resistances if x > price]
    below = [x for x in supports if x < price]
    if d == "UP":
        if not above:
            return None
        return {"direction": "UP", "target": min(above), "opposite": max(below) if below else None}
    if not below:
        return None
    return {"direction": "DOWN", "target": max(below), "opposite": min(above) if above else None}


def score(st: dict, bars: list, rec: datetime) -> dict:
    """bars: closed H1 bars [t, o, h, l, c] after recording, oldest first."""
    up = st["direction"] == "UP"
    t, o = st["target"], st.get("opposite")
    hit_h = opp_h = None
    for b in bars:
        h = (datetime.fromisoformat(b[0].replace("Z", "+00:00")) + timedelta(hours=1) - rec).total_seconds() / 3600
        tgt = b[2] >= t if up else b[3] <= t
        opp = o is not None and (b[3] <= o if up else b[2] >= o)
        if opp and opp_h is None:
            opp_h = h
        if tgt:
            hit_h = h
            break
    out = {"reached": hit_h is not None, "hours_to_target": round(hit_h, 1) if hit_h is not None else None,
           "opposite_first": opp_h is not None and (hit_h is None or opp_h <= hit_h)}
    for k, lim in CHECKS.items():
        out["in_" + k] = hit_h is not None and hit_h <= lim
    return out


def _canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _load(p: Path) -> list[dict]:
    lines = [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
    prev = "0" * 64
    for i, e in enumerate(lines, 1):
        body = {k: v for k, v in e.items() if k != "hash"}
        if e.get("seq") != i or e.get("prev") != prev or e["hash"] != hashlib.sha256((prev + _canon(body)).encode()).hexdigest():
            raise RuntimeError(f"{p} chain broken at {i}")
        prev = e["hash"]
    return lines


def _append(p: Path, lines: list, kind: str, data: dict, now: datetime) -> None:
    prev = lines[-1]["hash"] if lines else "0" * 64
    x = {"seq": len(lines) + 1, "kind": kind, "recorded_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": data, "prev": prev}
    x["hash"] = hashlib.sha256((prev + _canon({k: v for k, v in x.items() if k != "hash"})).encode()).hexdigest()
    lines.append(x)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fh.write(_canon(x) + "\n")


def record(snaps: dict, repo: Path, now: datetime, lines: list) -> int:
    p = repo / FILE
    last = {}
    for e in lines:
        if e["kind"] == "STATEMENT":
            last[(e["data"]["asset"], e["data"]["horizon"])] = _ts(e["recorded_at"])
    added = 0
    for a in ASSETS:
        s = snaps.get(a)
        if not s or s.get("price") is None or s.get("market_closed") or s.get("mode", "LIVE") != "LIVE":
            continue
        try:
            if not timedelta(0) <= now - _ts(s["as_of"]) <= STALE:
                continue
        except (KeyError, ValueError):
            continue
        for o in s.get("outlooks") or []:
            h = o.get("horizon")
            if h not in HORIZONS or "trend" not in o:
                continue
            if (a, h) in last and now - last[(a, h)] < EVERY:
                continue
            price = float(s["price"])
            st = statement(o.get("trend"), price, [float(x) for x in o.get("supports") or []],
                           [float(x) for x in o.get("resistances") or []])
            if st is None:
                continue
            _append(p, lines, "STATEMENT", {"version": VERSION, "asset": a, "horizon": h, "price": price,
                                            "trend": o.get("trend"), **st, "source_as_of": s["as_of"]}, now)
            last[(a, h)] = now
            added += 1
    return added


def settle(repo: Path, now: datetime, lines: list) -> int:
    p = repo / FILE
    done = {e["data"]["ref"] for e in lines if e["kind"] == "RESULT"}
    cache: dict = {}
    n = 0
    for e in list(lines):
        if e["kind"] != "STATEMENT" or e["seq"] in done:
            continue
        d = e["data"]
        rec = _ts(e["recorded_at"])
        f = repo / BARS[d["asset"]]
        if not f.exists():
            continue
        if d["asset"] not in cache:
            cache[d["asset"]] = json.loads(f.read_text())
        end = rec + timedelta(hours=MAX_H)
        bars = [b for b in cache[d["asset"]] if rec <= _ts(b[0]) and _ts(b[0]) + timedelta(hours=1) <= min(end, now)]
        r = score(d, bars, rec)
        if not r["reached"] and now < end + timedelta(hours=1):
            continue  # still open
        _append(p, lines, "RESULT", {"ref": e["seq"], "asset": d["asset"], "horizon": d["horizon"],
                                     "direction": d["direction"], "bars": len(bars), **r}, now)
        n += 1
    return n


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    if n < MIN_N:
        return {"n": n, "verdict": "INSUFFICIENT"}
    hrs = sorted(r["hours_to_target"] for r in rows if r["reached"])
    out = {"n": n, "verdict": "DESCRIBED"}
    for k in CHECKS:
        out["reached_" + k] = round(sum(1 for r in rows if r["in_" + k]) / n, 3)
    out["median_hours_to_target"] = hrs[len(hrs) // 2] if hrs else None
    out["opposite_first"] = round(sum(1 for r in rows if r["opposite_first"]) / n, 3)
    return out


def stats(lines: list) -> dict:
    rows = [e["data"] for e in lines if e["kind"] == "RESULT"]
    groups = sorted({(r["horizon"], r["direction"]) for r in rows})
    return {"version": VERSION, "statements": sum(1 for e in lines if e["kind"] == "STATEMENT"), "settled": len(rows),
            "by_horizon_direction": {f"{h}|{d}": summary([r for r in rows if r["horizon"] == h and r["direction"] == d])
                                     for h, d in groups},
            "by_asset_horizon_direction": {f"{a}|{h}|{d}": summary([r for r in rows if r["asset"] == a and r["horizon"] == h
                                                                    and r["direction"] == d])
                                           for a in ASSETS for h, d in groups
                                           if any(r["asset"] == a and r["horizon"] == h and r["direction"] == d for r in rows)}}


def apply(inp: str, repo: str = ".", now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rp = Path(repo)
    lines = _load(rp / FILE)
    snaps = {}
    for a in ASSETS:
        f = Path(inp) / f"snap_{a}.json"
        if f.exists():
            try:
                snaps[a] = json.loads(f.read_text())
            except ValueError:
                pass
    added = record(snaps, rp, now, lines)
    settled = settle(rp, now, lines)
    st = stats(lines)
    st["last_run"] = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "added": added, "settled": settled}
    (rp / "studies").mkdir(exist_ok=True)
    (rp / "studies" / "lean_targets_stats.json").write_text(json.dumps(st, indent=1, ensure_ascii=False) + "\n")
    return st


if __name__ == "__main__":
    import sys
    try:
        r = apply(sys.argv[1] if len(sys.argv) > 1 else ".", sys.argv[2] if len(sys.argv) > 2 else ".")
        print("lean targets:", r["last_run"])
    except Exception as e:  # noqa: BLE001  (never blocks the range ledger)
        print("lean targets failed:", e)
