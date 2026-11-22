#!/usr/bin/env python3
"""AI QUANT 2.0 — signal life cycle (signals-1): an append-only, hash-chained book of actionable signals.

A signal is issued once (idempotent: the same id is never issued twice) and every later change is a NEW dated line;
nothing is rewritten. The current state of a signal is the fold of its lines, so a restart rebuilds it exactly.

Statuses: PENDING -> ACTIVE -> TARGET | STOP | TIME_EXIT ;  PENDING -> EXPIRED_UNTRIGGERED | CANCELLED ;
          any open status -> DATA_INVALID (evaluation data missing; never a guessed result).
Updates: ACTIVATE (fill), EXTEND_TARGET / MOVE_STOP (each a new decision with its rule version and reason; the
original levels stay on record; a losing position can never be extended automatically), CANCEL, CLOSE.
Only activated signals count as wins or losses; EXPIRED_UNTRIGGERED and CANCELLED are counted separately.
Forecasts and paper results of other engines are not accepted here (layer must be SIGNAL).
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA = "signals-1"
OPEN = {"PENDING", "ACTIVE"}
FINAL = {"TARGET", "STOP", "TIME_EXIT", "EXPIRED_UNTRIGGERED", "CANCELLED", "DATA_INVALID"}
REQUIRED = ("id", "asset", "kind", "strategy", "rules_version", "issued_at", "ref_price", "trigger", "entry", "target",
            "stop", "expires_at", "costs", "data_source")
# te_live (te-live-h1-0.1) statuses -> signals-1 vocabulary, for display and unified statistics
TE_MAP = {"PENDING": "PENDING", "OPEN": "ACTIVE", "TARGET": "TARGET", "STOP": "STOP", "TIME": "TIME_EXIT",
          "NOT_FILLED": "EXPIRED_UNTRIGGERED", "NO_DATA": "DATA_INVALID"}


class SignalError(ValueError):
    pass


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Book:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lines = [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()] if self.path.exists() else []
        if not self.verify():
            raise SignalError("signal book chain broken")

    # -------------------------------------------------------------------------------------------- chain
    def verify(self) -> bool:
        prev = "0" * 64
        for i, e in enumerate(self.lines, 1):
            h = hashlib.sha256((prev + canon({k: v for k, v in e.items() if k != "hash"})).encode()).hexdigest()
            if e.get("seq") != i or e.get("prev") != prev or e.get("hash") != h:
                return False
            prev = e["hash"]
        return True

    def _append(self, kind: str, data: dict, at: str) -> dict:
        prev = self.lines[-1]["hash"] if self.lines else "0" * 64
        e = {"seq": len(self.lines) + 1, "kind": kind, "recorded_at": at, "schema": SCHEMA, "data": data, "prev": prev}
        e["hash"] = hashlib.sha256((prev + canon({k: v for k, v in e.items() if k != "hash"})).encode()).hexdigest()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(canon(e) + "\n")
        self.lines.append(e)
        return e

    # -------------------------------------------------------------------------------------------- state
    def state(self, sid: str) -> dict | None:
        s = None
        for e in self.lines:
            d = e["data"]
            if e["kind"] == "ISSUE" and d["id"] == sid:
                s = dict(d, status="PENDING", history=[], original={"target": d["target"], "stop": d["stop"]})
            elif s is not None and d.get("id") == sid:
                s["history"].append({"kind": e["kind"], "at": e["recorded_at"], **{k: v for k, v in d.items() if k != "id"}})
                if e["kind"] == "ACTIVATE":
                    s.update(status="ACTIVE", fill=d["fill"], filled_at=d["at"])
                elif e["kind"] == "EXTEND_TARGET":
                    s["target"] = d["target"]
                elif e["kind"] == "MOVE_STOP":
                    s["stop"] = d["stop"]
                elif e["kind"] == "CANCEL":
                    s["status"] = "CANCELLED"
                elif e["kind"] == "CLOSE":
                    s.update(status=d["status"], exit=d.get("exit"), net=d.get("net"), closed_at=d["at"], close_reason=d.get("reason"))
        return s

    def ids(self) -> list[str]:
        return [e["data"]["id"] for e in self.lines if e["kind"] == "ISSUE"]

    # -------------------------------------------------------------------------------------------- writes
    def issue(self, sig: dict, at: str, layer: str = "SIGNAL") -> bool:
        """Returns False (no-op) if this id was already issued — a repeated request never records twice."""
        if layer != "SIGNAL":
            raise SignalError("forecasts and paper results are not signals")
        miss = [k for k in REQUIRED if sig.get(k) is None]
        if miss:
            raise SignalError(f"missing fields: {miss}")
        if sig["id"] in self.ids():
            return False
        if not (sig["stop"] < sig["entry"] < sig["target"]):
            raise SignalError("long spot signal needs stop < entry < target")
        self._append("ISSUE", sig, at)
        return True

    def update(self, sid: str, kind: str, data: dict, at: str) -> dict:
        s = self.state(sid)
        if s is None:
            raise SignalError("unknown signal")
        if s["status"] in FINAL:
            raise SignalError(f"signal already {s['status']}: history is not rewritten")
        if kind == "ACTIVATE" and s["status"] != "PENDING":
            raise SignalError("only a pending signal can activate")
        if kind in ("EXTEND_TARGET", "MOVE_STOP"):
            if not data.get("rule_version") or not data.get("reason"):
                raise SignalError("a level change is a new decision: rule_version and reason required")
            if kind == "EXTEND_TARGET" and s["status"] == "ACTIVE" and data.get("price") is not None and data["price"] < s["fill"]:
                raise SignalError("a losing position is never extended to avoid recording a loss")
            if kind == "MOVE_STOP" and data["stop"] < s["stop"]:
                raise SignalError("a stop may only be raised (protect), never widened")
        if kind == "CANCEL" and s["status"] != "PENDING":
            raise SignalError("an active position closes with CLOSE, not CANCEL")
        if kind == "CLOSE":
            if data.get("status") not in FINAL - {"CANCELLED"}:
                raise SignalError("CLOSE needs a final status")
            if data["status"] in ("TARGET", "STOP", "TIME_EXIT") and s["status"] != "ACTIVE":
                raise SignalError("only an activated signal can win or lose")
            if data["status"] == "EXPIRED_UNTRIGGERED" and s["status"] != "PENDING":
                raise SignalError("an activated signal cannot expire untriggered")
        return self._append(kind, dict(data, id=sid), at)

    # -------------------------------------------------------------------------------------------- stats
    def stats(self, strategy: str | None = None, asset: str | None = None) -> dict:
        ss = [self.state(i) for i in self.ids()]
        ss = [s for s in ss if (strategy is None or s["strategy"] == strategy) and (asset is None or s["asset"] == asset)]
        closed = [s for s in ss if s["status"] in ("TARGET", "STOP", "TIME_EXIT")]
        nets = [s["net"] for s in closed if s.get("net") is not None]
        return {"issued": len(ss), "pending": sum(s["status"] == "PENDING" for s in ss), "active": sum(s["status"] == "ACTIVE" for s in ss),
                "activated_closed": len(closed), "wins": sum(1 for x in nets if x > 0), "losses": sum(1 for x in nets if x <= 0),
                "target": sum(s["status"] == "TARGET" for s in closed), "stop": sum(s["status"] == "STOP" for s in closed),
                "time_exit": sum(s["status"] == "TIME_EXIT" for s in closed),
                "expired_untriggered": sum(s["status"] == "EXPIRED_UNTRIGGERED" for s in ss),
                "cancelled": sum(s["status"] == "CANCELLED" for s in ss), "data_invalid": sum(s["status"] == "DATA_INVALID" for s in ss),
                "mean_net_pct": round(100 * sum(nets) / len(nets), 4) if nets else None}
