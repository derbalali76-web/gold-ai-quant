#!/usr/bin/env python3
"""beginner-ideas-0.1 — the public record of the app's «ماذا أفعل؟» ideas and of what happened after each one.

PRE-REGISTERED 2026-11-23 (owner request), before any idea was recorded or scored. Nothing below is changed after
results exist; a new version gets a new name.

WHAT IS RECORDED. Every hourly run, for each asset (XAU, BTC, ETH, SOL), each horizon (HOURS, WEEK, MONTH) and each
mode (cash, holder), the idea the app's rule gives (`decide`, a line-by-line copy of android SimpleAdvice.kt) from the
server's public snapshot: price, the horizon's nearest supports / resistances, the horizon's trend. A new IDEA is
recorded for a key (asset, horizon, mode) only when that key has no idea still inside its window, so ideas are a
time sample of what the app showed (one per window), never a choice made after seeing prices. No idea is recorded
when the snapshot is stale (> 2 h), the market is closed, the trend field is missing, or the rule gives NONE.
Windows: HOURS 24 h, WEEK 168 h, MONTH 720 h. Records are append-only and hash-chained; nothing is edited later.

HOW EACH IDEA IS SCORED (closed H1 bars after recording, through the window; a limit fills at its level or a better
open; a stop fills at its level or a worse open; a bar touching both target and stop counts as the stop).
Fees f per side: XAU 0.05 %, BTC 0.16 %, ETH 0.16 %, SOL 0.22 %. Each idea is compared with the obvious alternative.
  cash · BUY_NOW          buy at p0; sell at the target R or at the cancel level, else value at the last close.
                          alternative: stay in cash (0 %).                          metric: return % of the dollar
  cash · WAIT_DIP         limit buy at S; once bought, same exits as BUY_NOW; never filled = stayed in cash (0 %).
                          alternative: buy at p0 and hold to the last close.        metric: return %
  cash · WAIT             stay in cash (0 %).  alternative: buy at p0 and hold.     metric: return %
  holder · HOLD_SELL_ABOVE keep; sell at R if reached (then cash). alternative: sell now at p0.  metric: units after
                          fees valued at the last close (1 unit = kept)
  holder · SELL_REBUY     sell at p0, limit buy back at S; never reached = buy back at the last close (counted, and
                          flagged ROSE_NO_RETURN if the price went above p0).  alternative: keep (1 unit). metric: units
edge = idea − alternative (percentage points). SUCCESS when edge > 0 (WAIT: when edge >= 0).

VERDICT per idea kind (all assets and horizons together, and per horizon), shown only with n >= 30 scored ideas:
  USEFUL when mean edge > 0 AND success rate >= 50 %; otherwise NOT_USEFUL; below 30: INSUFFICIENT.
  Ideas of different horizons overlap in time; that is reported, not corrected. USEFUL is evidence to keep watching,
  not a proven edge. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

VERSION = "beginner-ideas-0.1"
ASSETS = ("XAU", "BTC", "ETH", "SOL")
HORIZONS = {"HOURS": 24, "WEEK": 168, "MONTH": 720}
FEE = {"XAU": 0.0005, "BTC": 0.0016, "ETH": 0.0016, "SOL": 0.0022}
BARS = {"XAU": "bars_H1.json", "BTC": "bars_BTC_H1.json", "ETH": "bars_ETH_H1.json", "SOL": "bars_SOL_H1.json"}
HIGH, LOW = 0.66, 0.25
MIN_N = 30
STALE = timedelta(hours=2)
FILE = Path("studies") / "beginner_ideas.jsonl"


# ---------------------------------------------------------------- the app's rule (copy of SimpleAdvice.kt)
def trend_code(d: Optional[str]) -> Optional[str]:
    return {"UP": "UP", "DOWN": "DOWN", "SIDEWAYS": "SIDEWAYS", "NEUTRAL": "SIDEWAYS"}.get(d or "")


def decide(trend: Optional[str], price: Optional[float], supports: list, resistances: list, hold: bool) -> dict:
    none = {"kind": "NONE", "buy_at": None, "sell_at": None, "invalid": None, "position": None}
    if price is None:
        return none
    p = float(price)
    below = [x for x in supports if x < p]
    above = [x for x in resistances if x > p]
    s = max(below) if below else (min(supports) if supports else None)
    r = min(above) if above else (max(resistances) if resistances else None)
    if s is None or r is None or r <= s:
        return none
    pos = min(1.0, max(0.0, (p - s) / (r - s)))
    high, low = pos > HIGH, pos < LOW
    lower = [x for x in supports if x < s]
    inv = max(lower) if lower else s * 0.985
    d = trend_code(trend)
    I = lambda k, b, se, i: {"kind": k, "buy_at": b, "sell_at": se, "invalid": i, "position": round(pos, 4)}  # noqa: E731
    if not hold:
        if d == "UP" and not high:
            return I("BUY_NOW", p, r, inv)
        if d == "UP":
            return I("WAIT_DIP", s, r, inv)
        if d == "SIDEWAYS" and low:
            return I("BUY_NOW", p, r, inv)
        return I("WAIT", s, None, inv)
    if d == "UP" and high:
        return I("SELL_REBUY", s, p, None)
    if d == "UP":
        return I("HOLD_SELL_ABOVE", None, r, inv)
    if low:
        return I("HOLD_SELL_ABOVE", None, r, inv)
    if d == "DOWN":
        return I("SELL_REBUY", s, p, None)
    if high:
        return I("SELL_REBUY", s, p, None)
    return I("HOLD_SELL_ABOVE", None, r, inv)


# ---------------------------------------------------------------- scoring
def _long(bars: list, entry: float, target: Optional[float], stop: Optional[float], f: float) -> tuple[float, str]:
    """Return of 1 dollar bought at `entry` (fee paid), closed at target / stop / last close (fee paid)."""
    for b in bars:
        hit_s = stop is not None and b[3] <= stop
        hit_t = target is not None and b[2] >= target
        if hit_s:
            px = min(stop, b[1])
            return px * (1 - f) / (entry * (1 + f)) - 1, "STOP"
        if hit_t:
            px = max(target, b[1])
            return px * (1 - f) / (entry * (1 + f)) - 1, "TARGET"
    return bars[-1][4] * (1 - f) / (entry * (1 + f)) - 1, "END"


def score(idea: dict, bars: list) -> Optional[dict]:
    """idea: IDEA data. bars: closed H1 bars [t, o, h, l, c] inside the window, oldest first."""
    if not bars:
        return None
    k, p0, f = idea["kind"], idea["price"], FEE[idea["asset"]]
    end = bars[-1][4]
    hold_ret = end * (1 - f) / (p0 * (1 + f)) - 1
    out: dict = {"end_close": end}
    if k == "BUY_NOW":
        r, how = _long(bars, p0, idea["sell_at"], idea["invalid"], f)
        out.update(idea_pct=r, alt_pct=0.0, exit=how)
    elif k == "WAIT_DIP":
        S = idea["buy_at"]
        j = next((i for i, b in enumerate(bars) if b[3] <= S), None)
        if j is None:
            out.update(idea_pct=0.0, alt_pct=hold_ret, exit="NOT_FILLED")
        else:
            entry = min(S, bars[j][1])
            rest = bars[j + 1:] or [bars[j]]
            r, how = _long(rest, entry, idea["sell_at"], idea["invalid"], f)
            out.update(idea_pct=r, alt_pct=hold_ret, exit=how)
    elif k == "WAIT":
        out.update(idea_pct=0.0, alt_pct=hold_ret, exit="WAITED")
    elif k == "HOLD_SELL_ABOVE":
        R = idea["sell_at"]
        j = next((i for i, b in enumerate(bars) if b[2] >= R), None)
        units = 1.0 if j is None else max(R, bars[j][1]) * (1 - f) / end
        alt = p0 * (1 - f) / end
        out.update(idea_pct=units - 1, alt_pct=alt - 1, exit="KEPT" if j is None else "SOLD_AT_TARGET")
    elif k == "SELL_REBUY":
        S = idea["buy_at"]
        j = next((i for i, b in enumerate(bars) if b[3] <= S), None)
        px = end if j is None else min(S, bars[j][1])
        units = p0 * (1 - f) / (px * (1 + f))
        rose = j is None and max(b[2] for b in bars) > p0
        out.update(idea_pct=units - 1, alt_pct=0.0, exit="REBOUGHT" if j is not None else "NO_REBUY",
                   rose_no_return=rose)
    else:
        return None
    out["edge_pct"] = out["idea_pct"] - out["alt_pct"]
    out["success"] = out["edge_pct"] >= 0 if k == "WAIT" else out["edge_pct"] > 0
    for x in ("idea_pct", "alt_pct", "edge_pct"):
        out[x] = round(100 * out[x], 4)
    return out


def verdict(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0, "verdict": "INSUFFICIENT"}
    me = sum(r["edge_pct"] for r in rows) / n
    sr = sum(1 for r in rows if r["success"]) / n
    v = "INSUFFICIENT" if n < MIN_N else ("USEFUL" if me > 0 and sr >= 0.5 else "NOT_USEFUL")
    return {"n": n, "mean_edge_pct": round(me, 3), "success_rate": round(sr, 3), "verdict": v}


# ---------------------------------------------------------------- chain
def _canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def record(snaps: dict, repo: Path, now: datetime, lines: list) -> int:
    """Record new IDEAs from {asset: snapshot}. Returns how many were added."""
    p = repo / FILE
    open_keys = {(e["data"]["asset"], e["data"]["horizon"], e["data"]["mode"]) for e in lines
                 if e["kind"] == "IDEA" and _ts(e["data"]["expires"]) > now}
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
            for mode in ("cash", "holder"):
                if (a, h, mode) in open_keys:
                    continue
                sup = [float(x) for x in o.get("supports") or []]
                res = [float(x) for x in o.get("resistances") or []]
                i = decide(o.get("trend"), s["price"], sup, res, mode == "holder")
                if i["kind"] == "NONE":
                    continue
                data = {"version": VERSION, "asset": a, "horizon": h, "mode": mode, "price": float(s["price"]),
                        "trend": o.get("trend"), "supports": sup, "resistances": res, **i,
                        "source_as_of": s["as_of"], "expires": (now + timedelta(hours=HORIZONS[h])).strftime("%Y-%m-%dT%H:%M:%SZ")}
                _append(p, lines, "IDEA", data, now)
                open_keys.add((a, h, mode))
                added += 1
    return added


def settle(repo: Path, now: datetime, lines: list) -> int:
    """Score every IDEA whose window is complete, once."""
    p = repo / FILE
    done = {e["data"]["ref"] for e in lines if e["kind"] == "IDEA_RESULT"}
    n = 0
    for e in list(lines):
        if e["kind"] != "IDEA" or e["seq"] in done:
            continue
        d = e["data"]
        rec, exp = _ts(e["recorded_at"]), _ts(d["expires"])
        f = repo / BARS[d["asset"]]
        if now < exp + timedelta(hours=1) or not f.exists():
            continue
        bars = [b for b in json.loads(f.read_text()) if rec <= _ts(b[0]) and _ts(b[0]) + timedelta(hours=1) <= exp]
        r = score(d, bars)
        _append(p, lines, "IDEA_RESULT", {"ref": e["seq"], "asset": d["asset"], "horizon": d["horizon"], "mode": d["mode"],
                                          "kind": d["kind"], "bars": len(bars), "outcome": "SCORED" if r else "NO_DATA",
                                          "result": r}, now)
        n += 1
    return n


def stats(lines: list) -> dict:
    rows = [dict(e["data"]["result"], kind=e["data"]["kind"], horizon=e["data"]["horizon"]) for e in lines
            if e["kind"] == "IDEA_RESULT" and e["data"]["outcome"] == "SCORED"]
    kinds = sorted({r["kind"] for r in rows})
    out = {"version": VERSION, "ideas": sum(1 for e in lines if e["kind"] == "IDEA"), "scored": len(rows),
           "by_kind": {k: verdict([r for r in rows if r["kind"] == k]) for k in kinds},
           "by_kind_horizon": {f"{k}|{h}": verdict([r for r in rows if r["kind"] == k and r["horizon"] == h])
                               for k in kinds for h in HORIZONS if any(r["kind"] == k and r["horizon"] == h for r in rows)}}
    sr = [r for r in rows if r["kind"] == "SELL_REBUY"]
    if sr:
        out["sell_rebuy_rose_no_return"] = round(sum(1 for r in sr if r.get("rose_no_return")) / len(sr), 3)
    return out


def apply(inp: str, repo: str = ".", now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    repo_p = Path(repo)
    lines = _load(repo_p / FILE)
    snaps = {}
    for a in ASSETS:
        f = Path(inp) / f"snap_{a}.json"
        if f.exists():
            try:
                snaps[a] = json.loads(f.read_text())
            except ValueError:
                pass
    added = record(snaps, repo_p, now, lines)
    scored = settle(repo_p, now, lines)
    st = stats(lines)
    st["last_run"] = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "added": added, "scored": scored,
                      "trend_in_snapshot": any("trend" in o for s in snaps.values() for o in s.get("outlooks") or [])}
    (repo_p / "studies").mkdir(exist_ok=True)
    (repo_p / "studies" / "beginner_ideas_stats.json").write_text(json.dumps(st, indent=1, ensure_ascii=False) + "\n")
    return st


if __name__ == "__main__":
    import sys
    try:
        r = apply(sys.argv[1] if len(sys.argv) > 1 else ".", sys.argv[2] if len(sys.argv) > 2 else ".")
        print("beginner ideas:", r["last_run"])
    except Exception as e:  # noqa: BLE001  (never blocks the range ledger)
        print("beginner ideas failed:", e)
