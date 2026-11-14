#!/usr/bin/env python3
"""AI QUANT public trust ledger — standard library only, so anyone can read and re-run it.

Every hour a workflow fetches the app server's public snapshot and runs `python ledger.py update snapshot.json`:
  * a validated recommendation (REC) is appended the moment it is published — BEFORE its outcome exists;
  * the day's analysis (BRIEF: bias UP/DOWN/SIDEWAYS) is appended once per day, before that day closes;
  * when the price later reaches the stop, the target, or the time limit, a RESULT line is appended.
Lines are never edited or deleted. Each line carries the SHA-256 of the previous one, so changing any old line
breaks every hash after it, and every line is in a git commit whose time GitHub records.

`python ledger.py verify` re-checks the whole chain and recomputes stats.json from the lines alone.

Rules (deliberately conservative):
  * MARKET entry = the snapshot price at the recording time; LIMIT entry fills only if a later bar trades into the
    entry zone before the plan expires (otherwise NOT_FILLED, excluded from wins and losses).
  * Only bars that OPEN after the recording time are used (no look-ahead into the current bar).
  * If one bar touches both the stop and the target, the STOP is counted.
  * Results are in R (multiples of the initial risk) after the published cost per ounce.
  * Baseline: the same entry/stop/target distances, always taken as a BUY — does choosing the direction add value
    over gold's long-term upward drift?
  * BRIEF is scored at that day's close: UP correct if close > recorded price, DOWN correct if close < it.
    SIDEWAYS/UNKNOWN are not scored. Baseline: "always UP" on the same days.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

GENESIS = "0" * 64
TF_MIN = {"H1": 60, "D1": 1440}
KEEP = {"H1": 3000, "D1": 600}
DEFAULT_LIFE = {"HOURS": timedelta(hours=8), "WEEK": timedelta(days=7), "MONTH": timedelta(days=31)}
RES_TF = {"HOURS": "H1", "WEEK": "D1", "MONTH": "D1"}
MAX_SNAPSHOT_AGE = timedelta(hours=2)


# ---------------------------------------------------------------- helpers
def ts(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def weekend(t: datetime) -> bool:
    """Bar opening inside the weekly close (Fri 21:00 -> Sun 22:00 UTC): some feeds print flat weekend quotes."""
    d, h = t.weekday(), t.hour
    return d == 5 or (d == 4 and h >= 21) or (d == 6 and h < 22)


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def line_hash(e: dict) -> str:
    body = {k: e[k] for k in ("seq", "recorded_at", "kind", "data", "prev")}
    return hashlib.sha256(canon(body).encode("utf-8")).hexdigest()


class Ledger:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "ledger.jsonl"
        self.entries: list[dict] = []
        if self.path.exists():
            for raw in self.path.read_text(encoding="utf-8").splitlines():
                if raw.strip():
                    self.entries.append(json.loads(raw))
        self.bars = {tf: self._load_bars(tf) for tf in TF_MIN}

    # -------- storage
    def _bars_path(self, tf):
        return self.root / f"bars_{tf}.json"

    def _load_bars(self, tf) -> dict:
        p = self._bars_path(tf)
        rows = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        return {r[0]: r for r in rows if not weekend(ts(r[0]))}

    def head(self) -> str:
        return self.entries[-1]["hash"] if self.entries else GENESIS

    def append(self, kind: str, data: dict, now: datetime) -> dict:
        e = {"seq": len(self.entries) + 1, "recorded_at": iso(now), "kind": kind, "data": data, "prev": self.head()}
        e["hash"] = line_hash(e)
        self.entries.append(e)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(canon(e) + "\n")
        return e

    def save_bars(self):
        for tf, rows in self.bars.items():
            keep = [rows[k] for k in sorted(rows)][-KEEP[tf]:]
            self.bars[tf] = {r[0]: r for r in keep}
            self._bars_path(tf).write_text(json.dumps(keep, separators=(",", ":")), encoding="utf-8")

    # -------- verification
    def verify(self) -> list[str]:
        errs, prev, recs = [], GENESIS, {}
        for i, e in enumerate(self.entries, 1):
            if e.get("seq") != i:
                errs.append(f"line {i}: seq {e.get('seq')} != {i}")
            if e.get("prev") != prev:
                errs.append(f"line {i}: prev hash does not match line {i - 1}")
            if line_hash(e) != e.get("hash"):
                errs.append(f"line {i}: content does not match its hash (edited?)")
            if e["kind"] in ("REC", "BRIEF"):
                recs[e["seq"]] = e
            elif e["kind"] in ("RESULT", "BRIEF_RESULT"):
                ref = recs.get(e["data"].get("ref"))
                if ref is None:
                    errs.append(f"line {i}: result for unknown line {e['data'].get('ref')}")
                elif ts(e["recorded_at"]) < ts(ref["recorded_at"]):
                    errs.append(f"line {i}: result recorded before its recommendation")
            prev = e.get("hash")
        return errs

    # -------- queries
    def open_items(self, kind: str) -> list[dict]:
        done = {e["data"]["ref"] for e in self.entries if e["kind"] in ("RESULT", "BRIEF_RESULT")}
        return [e for e in self.entries if e["kind"] == kind and e["seq"] not in done]

    def sorted_bars(self, tf: str) -> list[tuple[datetime, float, float, float, float]]:
        return [(ts(r[0]), *map(float, r[1:5])) for _, r in sorted(self.bars[tf].items())]

    # -------- update
    def ingest(self, snap: dict, now: datetime) -> list[dict]:
        """Merge closed bars, record new RECs / BRIEF, then resolve what can be resolved. Returns new lines."""
        before = len(self.entries)
        as_of = ts(snap["as_of"])
        for tf in TF_MIN:
            step = timedelta(minutes=TF_MIN[tf])
            for r in (snap.get("bars") or {}).get(tf, []):
                t = ts(r[0])
                o, h, l, c = map(float, r[1:5])
                if t + step <= min(as_of, now) and not weekend(t) and l <= min(o, c) and h >= max(o, c) and l > 0:
                    self.bars[tf][iso(t)] = [iso(t), o, h, l, c]
        fresh = timedelta(0) <= now - as_of <= MAX_SNAPSHOT_AGE and snap.get("price") is not None
        if fresh:
            self._record_recs(snap, now)
            self._record_brief(snap, now)
        self._resolve(now)
        self.save_bars()
        return self.entries[before:]

    def _record_recs(self, snap, now):
        open_h = {e["data"]["horizon"] for e in self.open_items("REC")}
        for r in snap.get("recommendations") or []:
            hz, side = r.get("horizon"), r.get("side")
            stop, target = r.get("stop"), r.get("target")
            if hz not in DEFAULT_LIFE or side not in ("BUY", "SELL") or hz in open_h or not stop or not target:
                continue
            price = float(snap["price"])
            expires = ts(r["valid_until"]) if r.get("valid_until") else now + DEFAULT_LIFE[hz]
            expires = min(max(expires, now + timedelta(hours=1)), now + DEFAULT_LIFE[hz] * 2)
            d = 1 if side == "BUY" else -1
            if (target - price) * d <= 0 or (price - stop) * d <= 0:
                if r.get("order", "MARKET") == "MARKET":
                    continue  # already past the stop or the target: not a valid market entry
            self.append("REC", {
                "horizon": hz, "side": side, "order": r.get("order") or "MARKET",
                "price_at_record": price, "entry_low": r.get("entry_low"), "entry_high": r.get("entry_high"),
                "stop": float(stop), "target": float(target), "expires": iso(expires),
                "cost": float(snap.get("cost") or 0.0), "method": r.get("method"),
                "model_version": r.get("model_version") or snap.get("model_version"),
                "symbol": snap.get("symbol", "XAUUSD"), "source_as_of": snap["as_of"]}, now)
            open_h.add(hz)

    def _record_brief(self, snap, now):
        b = snap.get("brief")
        if not b or snap.get("market_closed") or b.get("bias") not in ("UP", "DOWN", "SIDEWAYS", "UNKNOWN"):
            return
        day = b.get("date")
        if day != now.date().isoformat():
            return  # only today's brief, recorded before today's close (no look-ahead)
        if any(e["kind"] == "BRIEF" and e["data"]["date"] == day for e in self.entries):
            return
        self.append("BRIEF", {"date": day, "bias": b["bias"], "price_at_record": float(snap["price"]),
                              "scenarios": b.get("scenarios") or [],
                              "model_version": snap.get("model_version"), "source_as_of": snap["as_of"]}, now)

    def _resolve(self, now):
        for e in self.open_items("REC"):
            out = simulate(e["data"], ts(e["recorded_at"]), self.sorted_bars(RES_TF[e["data"]["horizon"]]), now)
            if out is None:
                continue
            base = simulate(baseline_of(e["data"]), ts(e["recorded_at"]),
                            self.sorted_bars(RES_TF[e["data"]["horizon"]]), now)
            out["ref"] = e["seq"]
            out["baseline_r"] = None if base is None else base.get("r")
            self.append("RESULT", out, now)
        d1 = {b[0].date().isoformat(): b for b in self.sorted_bars("D1")}
        for e in self.open_items("BRIEF"):
            bar = d1.get(e["data"]["date"])
            if bar is None:
                if now - ts(e["recorded_at"]) > timedelta(days=5):
                    self.append("BRIEF_RESULT", {"ref": e["seq"], "outcome": "NO_DATA"}, now)
                continue
            close, p, bias = bar[4], e["data"]["price_at_record"], e["data"]["bias"]
            if bias in ("UP", "DOWN"):
                ok = close > p if bias == "UP" else close < p
                outcome = "CORRECT" if ok else "WRONG"
            else:
                outcome = "NOT_SCORED"
            self.append("BRIEF_RESULT", {"ref": e["seq"], "outcome": outcome, "close": close,
                                         "baseline_up_correct": close > p}, now)


def baseline_of(r: dict) -> dict:
    """The same distances, always as a BUY."""
    if r["side"] == "BUY":
        return dict(r)
    p = r["price_at_record"]
    lo, hi = r.get("entry_low"), r.get("entry_high")
    return dict(r, side="BUY", stop=2 * p - r["stop"], target=2 * p - r["target"],
                entry_low=None if hi is None else 2 * p - hi, entry_high=None if lo is None else 2 * p - lo)


def simulate(r: dict, recorded: datetime, bars: list, now: datetime) -> dict | None:
    """Outcome of a recorded plan on bars that open after `recorded`. None while still undecided."""
    d = 1 if r["side"] == "BUY" else -1
    expires = ts(r["expires"])
    step = timedelta(minutes=TF_MIN["H1" if r["horizon"] == "HOURS" else "D1"])
    later = [b for b in bars if b[0] >= recorded and b[0] + step <= now]
    entry, i0 = None, 0
    if r["order"] == "MARKET":
        entry = r["price_at_record"]
    else:
        lo, hi = r.get("entry_low"), r.get("entry_high")
        lo = hi if lo is None else lo
        hi = lo if hi is None else hi
        if lo is None:
            return {"outcome": "NOT_FILLED", "r": None, "reason": "no entry zone"}
        for i, b in enumerate(later):
            if b[0] >= expires:
                break
            if b[3] <= hi and b[2] >= lo:  # the bar traded inside the zone
                entry = min(hi, max(lo, b[1])) if d == 1 else max(lo, min(hi, b[1]))
                i0 = i
                break
        if entry is None:
            if later and later[-1][0] + step >= expires or now >= expires:
                return {"outcome": "NOT_FILLED", "r": None}
            return None
    risk = abs(entry - r["stop"])
    if risk <= 0:
        return {"outcome": "INVALID", "r": None}
    cost = float(r.get("cost") or 0.0)
    for b in later[i0:]:
        t, o, h, l, c = b
        if t >= expires:
            break
        hit_stop = (l <= r["stop"]) if d == 1 else (h >= r["stop"])
        hit_tgt = (h >= r["target"]) if d == 1 else (l <= r["target"])
        if hit_stop:  # also when both are touched in the same bar
            exit_ = o if (o - r["stop"]) * d < 0 else r["stop"]
            return _res("STOP", entry, exit_, d, risk, cost, t + step)
        if hit_tgt:
            return _res("TARGET", entry, r["target"], d, risk, cost, t + step)
    done = [b for b in later[i0:] if b[0] < expires]
    if now >= expires or (done and done[-1][0] + 2 * step > expires):
        if not done:
            return {"outcome": "NO_DATA", "r": None}
        return _res("TIMEOUT", entry, done[-1][4], d, risk, cost, done[-1][0] + step)
    return None


def _res(outcome, entry, exit_, d, risk, cost, when):
    r = ((exit_ - entry) * d - cost) / risk
    return {"outcome": outcome, "entry": round(entry, 2), "exit": round(exit_, 2), "r": round(r, 3),
            "closed_bar": iso(when)}


# ---------------------------------------------------------------- stats
def stats(entries: list[dict], now: datetime) -> dict:
    recs = {e["seq"]: e for e in entries if e["kind"] == "REC"}
    briefs = {e["seq"]: e for e in entries if e["kind"] == "BRIEF"}
    res = [e for e in entries if e["kind"] == "RESULT"]
    bres = [e for e in entries if e["kind"] == "BRIEF_RESULT"]

    def block(rows):
        scored = [x for x in rows if x["data"].get("r") is not None]
        wins = [x for x in scored if x["data"]["r"] > 0]
        rs = [x["data"]["r"] for x in scored]
        base = [x["data"]["baseline_r"] for x in scored if x["data"].get("baseline_r") is not None]
        eq, peak, dd = 0.0, 0.0, 0.0
        for v in rs:
            eq += v
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        return {"completed": len(scored), "wins": len(wins), "losses": len(scored) - len(wins),
                "targets": sum(1 for x in scored if x["data"]["outcome"] == "TARGET"),
                "stops": sum(1 for x in scored if x["data"]["outcome"] == "STOP"),
                "timeouts": sum(1 for x in scored if x["data"]["outcome"] == "TIMEOUT"),
                "not_filled": sum(1 for x in rows if x["data"]["outcome"] == "NOT_FILLED"),
                "win_rate": round(len(wins) / len(scored), 4) if scored else None,
                "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
                "total_r": round(sum(rs), 3) if rs else None,
                "max_drawdown_r": round(dd, 3) if rs else None,
                "baseline_avg_r": round(sum(base) / len(base), 3) if base else None}

    by_model: dict[str, list] = {}
    for x in res:
        by_model.setdefault(str(recs[x["data"]["ref"]]["data"].get("model_version")), []).append(x)
    by_hz: dict[str, list] = {}
    for x in res:
        by_hz.setdefault(recs[x["data"]["ref"]]["data"]["horizon"], []).append(x)
    scored_b = [x for x in bres if x["data"]["outcome"] in ("CORRECT", "WRONG")]
    first = entries[0]["recorded_at"] if entries else None
    done_refs = {x["data"]["ref"] for x in res}
    recent = []
    for x in res[-30:][::-1]:
        r = recs[x["data"]["ref"]]["data"]
        recent.append({"seq": x["data"]["ref"], "recorded_at": recs[x["data"]["ref"]]["recorded_at"],
                       "horizon": r["horizon"], "side": r["side"], "outcome": x["data"]["outcome"],
                       "r": x["data"].get("r"), "model_version": r.get("model_version")})
    return {
        "schema": 1, "updated_at": iso(now), "chain_head": entries[-1]["hash"] if entries else GENESIS,
        "lines": len(entries), "tracking_since": first,
        "days_tracked": (now - ts(first)).days if first else 0,
        "recommendations": dict(block(res), published=len(recs),
                                open=sum(1 for s in recs if s not in done_refs)),
        "by_horizon": {k: block(v) for k, v in sorted(by_hz.items())},
        "by_model": {k: block(v) for k, v in sorted(by_model.items())},
        "analysis": {"days": len(briefs), "scored": len(scored_b),
                     "correct": sum(1 for x in scored_b if x["data"]["outcome"] == "CORRECT"),
                     "accuracy": round(sum(1 for x in scored_b if x["data"]["outcome"] == "CORRECT") / len(scored_b), 4)
                     if scored_b else None,
                     "baseline_accuracy": round(sum(1 for x in scored_b if x["data"]["baseline_up_correct"]) / len(scored_b), 4)
                     if scored_b else None},
        "recent": recent,
    }


def write_stats(led: Ledger, now: datetime) -> dict:
    s = stats(led.entries, now)
    (led.root / "stats.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return s


def main(argv):
    root = Path(__file__).resolve().parent
    now = datetime.now(timezone.utc)
    led = Ledger(root)
    errs = led.verify()
    if argv[:1] == ["verify"]:
        recomputed = stats(led.entries, now)
        stored = json.loads((root / "stats.json").read_text(encoding="utf-8")) if (root / "stats.json").exists() else {}
        for k in ("chain_head", "lines", "recommendations", "analysis", "by_model"):
            if k in stored and canon(stored[k]) != canon(recomputed[k]):
                errs.append(f"stats.json '{k}' does not match the ledger")
        print("\n".join(errs) if errs else f"OK — {len(led.entries)} lines, head {led.head()[:16]}…")
        return 1 if errs else 0
    if argv[:1] == ["update"] and len(argv) == 2:
        if errs:
            print("refusing to append to a broken chain:\n" + "\n".join(errs))
            return 1
        snap = None
        try:
            snap = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — server asleep/unreachable: still resolve on stored bars
            print(f"no snapshot ({exc}); resolving on stored bars only")
        new = led.ingest(snap, now) if snap and snap.get("as_of") else (led._resolve(now) or [])
        write_stats(led, now)
        print(f"{len(new) if isinstance(new, list) else 0} new lines; head {led.head()[:16]}…")
        return 0
    print("usage: ledger.py update SNAPSHOT.json | ledger.py verify")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
