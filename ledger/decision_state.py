#!/usr/bin/env python3
"""AI QUANT 2.0 — one decision state per asset, for «ماذا أفعل؟» and «فرص التداول» alike (schema decision-state-1).

It does not invent decisions. It reads what the ledger already records and puts it into one structure with three
clearly separated layers, each with its own evidence stage:

  scenario     the likely scenario of advice-0.1.0 (a FORECAST: HOURS / WEEK views, triggers, likely side)
  action       what that scenario means for the user's position — one market signal, two personalised actions:
                 holder: SELL_OWNED (+ REBUY level) | HOLD (+ sell-higher level) | WAIT
                 cash:   BUY | WAIT (+ buy-lower level)
               A pre-emptive SELL_OWNED before a support breaks is allowed: it is advice-0.1.0's own instruction.
               Its stage says how much evidence stands behind it:
                 SCENARIO   recorded and being scored, verdict not reached (shown as a scenario, not as proven)
                 QUALIFIED  the instruction's own scored record PASSED its pre-registered rule (advice.stats)
                 FAILED     its record failed — kept visible as information, never as a recommendation
                 BLOCKED    a gate failed (stale or missing data, conflicting sides) -> WAIT / HOLD only
  opportunity  the experimental paper trade of te_live (stage PAPER_TEST until its own pass rule is met)

PAXG (and any asset without a qualified engine) carries price only: no scenario, no action beyond WAIT / HOLD.
One market signal produces at most one recorded STATE per change: holder and cash actions share its signal id,
so a single signal is never counted as two trades.

usage: decision_state.py fetch OUT_DIR            (network: PAXG price -> OUT_DIR/prices.json)
       decision_state.py apply IN_DIR [REPO]      (deterministic: decision/state.json + decision/states.jsonl)
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = "decision-state-2"   # -2 adds the presentation layer `view` + `radar` (2026-11-22); -1 lines stay as recorded
ASSETS = ("XAU", "BTC", "ETH", "SOL", "PAXG")
BARS = {"XAU": "bars_H1.json", "BTC": "bars_BTC_H1.json", "ETH": "bars_ETH_H1.json", "SOL": "bars_SOL_H1.json"}
PRICE_ONLY = {"PAXG"}
KLINES = "https://data-api.binance.vision/api/v3/klines?symbol=PAXGUSDT&interval=1h&limit=2"
ADVICE_MAX_AGE = timedelta(hours=30)   # a day's advice is valid until the next day's record (+ slack)
PRICE_MAX_AGE = timedelta(hours=3)

HOLD_MAP = {"SELL_NOW": "SELL_OWNED", "KEEP_SELL_HIGHER": "HOLD", "NOTHING": "HOLD"}
CASH_MAP = {"BUY_NOW": "BUY", "WAIT_BUY_LOWER": "WAIT", "DONT_BUY": "WAIT", "NOTHING": "WAIT"}
SIDE = {"SELL_NOW": "DOWN", "WAIT_BUY_LOWER": "DOWN", "DONT_BUY": "DOWN", "KEEP_SELL_HIGHER": "UP", "BUY_NOW": "UP"}


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ------------------------------------------------------------------------------------------------ pure logic
def market_signal(advice: dict | None) -> dict | None:
    """One market signal from one ADVICE record (hold and cash come from the same decision)."""
    if not advice:
        return None
    h, c = advice["hold"]["advice"], advice["cash"]["advice"]
    sides = {SIDE.get(h), SIDE.get(c)} - {None}
    kind = "NO_EDGE" if not sides else ("CONFLICT" if len(sides) > 1 else ("DOWN_MOVE" if sides == {"DOWN"} else "UP_MOVE"))
    sid = hashlib.sha256(canon({"a": advice["asset"], "d": advice["date"], "h": h, "c": c}).encode()).hexdigest()[:12]
    return {"id": sid, "kind": kind, "hold_advice": h, "cash_advice": c, "hold": advice["hold"], "cash": advice["cash"]}


def stage_of(stats: dict, asset: str, side: str, adv: str) -> str:
    c = (((stats or {}).get("assets") or {}).get(asset) or {}).get(side, {}).get(adv) or {}
    return {"PASS": "QUALIFIED", "FAIL": "FAILED"}.get(c.get("verdict"), "SCENARIO")


def actions(sig: dict | None, asset: str, stats: dict, gates_ok: bool, gate_reason: str | None) -> dict:
    """Personalised actions. Invariants: holder never BUY/short; cash never SELL_OWNED; one signal, no contradiction."""
    hold = {"action": "HOLD", "stage": "NONE", "level": None, "rebuy_at": None, "reason": "no_signal"}
    cash = {"action": "WAIT", "stage": "NONE", "level": None, "reason": "no_signal"}
    if sig is None or asset in PRICE_ONLY:
        reason = "price_only_asset" if asset in PRICE_ONLY else "no_signal"
        hold["reason"] = cash["reason"] = reason
        return {"holder": hold, "cash": cash, "signal_id": None}
    if not gates_ok or sig["kind"] == "CONFLICT":
        r = gate_reason if not gates_ok else "conflicting_sides"
        hold.update(stage="BLOCKED", reason=r)
        cash.update(stage="BLOCKED", reason=r)
        return {"holder": hold, "cash": cash, "signal_id": sig["id"]}
    ha, ca = sig["hold_advice"], sig["cash_advice"]
    hold = {"action": HOLD_MAP.get(ha, "HOLD"), "stage": "NONE" if ha == "NOTHING" else stage_of(stats, asset, "hold", ha),
            "level": sig["hold"].get("exit") if ha == "SELL_NOW" else sig["hold"].get("at"),
            "rebuy_at": sig["hold"].get("at") if ha == "SELL_NOW" else None, "advice": ha, "reason": "advice-0.1.0"}
    cash = {"action": CASH_MAP.get(ca, "WAIT"), "stage": "NONE" if ca == "NOTHING" else stage_of(stats, asset, "cash", ca),
            "level": sig["cash"].get("at"), "advice": ca, "reason": "advice-0.1.0"}
    for a in (hold, cash):          # a failed record is information, never a recommendation
        if a["stage"] == "FAILED":
            a["action"] = "HOLD" if a is hold else "WAIT"
    return {"holder": hold, "cash": cash, "signal_id": sig["id"]}


# ------------------------------------------------------------------------- presentation (decision-state-2)
# What the app shows. Approved by the owner 2026-11-22 (phase 4 design):
#   * the likely scenario is always shown (layer `scenario`, a FORECAST) — it never becomes an order by itself;
#   * an executive decision is shown ONLY for a QUALIFIED action with every gate open; otherwise the verdict is WAIT
#     with the reasons why no trade is approved;
#   * a cash user is never told to sell; a holder may be told to sell BEFORE a break (pre-emptive) when that exact
#     instruction is qualified, with the buy-back level and the invalidation level;
#   * the radar lists what is forming / qualified / rejected / expired; a QUALIFIED radar item exists iff a non-WAIT
#     verdict with the same signal id exists (one state everywhere);
#   * durations are adaptive (until the record's own expiry, which can exceed 24 h); no daily quota.
def _hours_left(advice: dict | None, now: datetime):
    if not advice or not advice.get("expires"):
        return None
    return max(0, round((ts(advice["expires"]) - now).total_seconds() / 3600))


def view(asset: str, act: dict, advice: dict | None, price: dict | None, gates: dict, now: datetime) -> dict:
    sid, h, c = act.get("signal_id"), act["holder"], act["cash"]
    p = (price or {}).get("value")
    dur = _hours_left(advice, now)
    sup = (((advice or {}).get("hours") or {}).get("down") or [None])[0]

    def why(a: dict) -> list:
        if asset in PRICE_ONLY:
            return ["price_only_asset"]
        if not gates["ok"]:
            return ["blocked:" + r for r in gates["reasons"]] or ["blocked"]
        if a["stage"] == "BLOCKED":
            return ["blocked:" + (a.get("reason") or "")]
        if sid is None:
            return ["no_signal"]
        if a["stage"] == "NONE":
            return ["no_edge"]
        if a["stage"] == "FAILED":
            return ["record_failed"]
        return ["not_yet_qualified"]

    out = {"holder": {"verdict": "WAIT", "signal_id": sid, "plan": None, "why": []},
           "cash": {"verdict": "WAIT", "signal_id": sid, "plan": None, "why": []}}
    ok = gates["ok"] and p is not None and asset not in PRICE_ONLY
    if ok and h["stage"] == "QUALIFIED" and h["action"] == "SELL_OWNED" and h.get("rebuy_at") is not None:
        out["holder"].update(verdict="SELL_THEN_REBUY", plan={"sell": p, "rebuy_at": h["rebuy_at"],
                             "invalidate_above": h.get("level"), "duration_h": dur, "adaptive": True})
    else:
        out["holder"]["why"] = why(h) if h["action"] != "HOLD" or h["stage"] != "QUALIFIED" else ["hold_is_the_plan"]
    if ok and c["stage"] == "QUALIFIED" and c.get("advice") in ("BUY_NOW", "WAIT_BUY_LOWER"):
        buy_now = c["advice"] == "BUY_NOW"
        entry = p if buy_now else c.get("level")
        tgt = ((advice or {}).get("cash") or {}).get("exit") if buy_now else None
        if entry is not None:
            out["cash"].update(verdict="BUY" if buy_now else "BUY_LIMIT", plan={"entry": entry, "target": tgt,
                               "invalidate_below": sup if (sup is not None and sup < entry) else None,
                               "duration_h": dur, "adaptive": True})
    if out["cash"]["verdict"] == "WAIT":
        out["cash"]["why"] = why(c)
    for k in ("holder", "cash"):
        if out[k]["verdict"] == "WAIT":
            out[k]["signal_id"] = sid if out[k]["why"] and out[k]["why"][0] in ("not_yet_qualified", "record_failed") else None
    assert out["cash"]["verdict"] in ("BUY", "BUY_LIMIT", "WAIT")    # never a sell for a cash user
    return out


RADAR_STATE = {"SCENARIO": "FORMING", "QUALIFIED": "QUALIFIED", "FAILED": "REJECTED"}


def radar(asset: str, act: dict, v: dict, te: dict | None) -> list:
    items, sid = [], act.get("signal_id")
    if sid and asset not in PRICE_ONLY and act["holder"]["stage"] != "BLOCKED":
        qual = any(v[k]["verdict"] != "WAIT" for k in ("holder", "cash"))
        stages = [act[k]["stage"] for k in ("holder", "cash") if act[k]["stage"] in RADAR_STATE]
        if qual:
            st = "QUALIFIED"
        elif "SCENARIO" in stages:
            st = "FORMING"
        elif "FAILED" in stages:
            st = "REJECTED"
        else:
            st = None
        if st:
            items.append({"id": sid, "source": "advice-0.1.0", "state": st,
                          "holder": act["holder"].get("action"), "cash": act["cash"].get("action"),
                          "level": act["holder"].get("rebuy_at") or act["cash"].get("level")})
    if te and te.get("asset") == asset:
        a = (te.get("active") or [None])[0]
        if a:
            items.append({"id": "te-%s" % a.get("seq"), "source": te.get("engine"), "state": "FORMING", "stage": "PAPER_TEST",
                          "entry": a.get("limit"), "target": a.get("target"), "invalidate_below": a.get("stop"),
                          "status": a.get("status")})
        lc = te.get("last_closed") or {}
        if lc.get("status") == "NOT_FILLED":
            items.append({"id": "te-%s" % lc.get("seq"), "source": te.get("engine"), "state": "EXPIRED", "stage": "PAPER_TEST"})
    return items


def build(asset: str, advice: dict | None, stats: dict, price: dict | None, te: dict | None, now: datetime) -> dict:
    gates, reasons = True, []
    if price is None or now - ts(price["at"]) > PRICE_MAX_AGE:
        gates, reasons = False, reasons + ["stale_or_missing_price"]
    if advice is not None and now - ts(advice["recorded_at"]) > ADVICE_MAX_AGE:
        gates, reasons, advice = False, reasons + ["stale_advice"], None
    sig = market_signal(advice) if asset not in PRICE_ONLY else None
    act = actions(sig, asset, stats, gates, ",".join(reasons) or None)
    scenario = None
    if advice:
        scenario = {"source": advice.get("version"), "recorded_at": advice["recorded_at"], "hours": advice.get("hours"),
                    "week": advice.get("week"), "stage": "FORECAST"}
    opp = None
    if te and asset == te.get("asset"):
        a = (te.get("active") or [None])[0]
        opp = {"engine": te.get("engine"), "stage": "PAPER_TEST", "active": a, "record": te.get("record")}
    g = {"ok": gates, "reasons": reasons}
    v = view(asset, act, advice, price, g, now)
    return {"asset": asset, "price": price, "scenario": scenario, "signal": None if sig is None else {k: sig[k] for k in ("id", "kind")},
            "actions": act, "view": v, "radar": radar(asset, act, v, te), "opportunity": opp, "gates": g}


def signature(s: dict) -> str:
    """What counts as a change worth a ledger line (prices move every hour; decisions do not)."""
    a = s["actions"]
    keep = {"sig": s["signal"], "h": {k: a["holder"].get(k) for k in ("action", "stage", "level", "rebuy_at")},
            "c": {k: a["cash"].get(k) for k in ("action", "stage", "level")}, "g": s["gates"]["ok"],
            "o": None if not s["opportunity"] else (s["opportunity"]["active"] or {}).get("seq"),
            "v": {k: s["view"][k]["verdict"] for k in ("holder", "cash")} if "view" in s else None}
    return hashlib.sha256(canon(keep).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------------------------- ledger inputs
def latest_advice(ledger_path: Path) -> dict:
    out = {}
    if ledger_path.exists():
        for line in ledger_path.read_text().splitlines():
            if '"ADVICE"' not in line:
                continue
            e = json.loads(line)
            if e.get("kind") == "ADVICE":
                out[e["data"]["asset"]] = dict(e["data"], recorded_at=e["recorded_at"], seq=e["seq"])
    return out


def last_price(repo: Path, asset: str, extra: dict) -> dict | None:
    if asset in extra:
        return extra[asset]
    f = repo / BARS.get(asset, "-")
    if not f.exists():
        return None
    bars = json.loads(f.read_text())
    if not bars:
        return None
    t, c = bars[-1][0], bars[-1][4]
    return {"value": c, "at": iso(ts(t) + timedelta(hours=1))}


def chain_lines(repo: Path) -> list:
    p = repo / "decision" / "states.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def verify(repo: Path) -> bool:
    prev = "0" * 64
    for i, e in enumerate(chain_lines(repo), 1):
        h = hashlib.sha256((prev + canon({k: v for k, v in e.items() if k != "hash"})).encode()).hexdigest()
        if e.get("seq") != i or e.get("prev") != prev or e.get("hash") != h:
            return False
        prev = e["hash"]
    return True


def apply(in_dir: Path, repo: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if not verify(repo):
        raise RuntimeError("decision/states.jsonl chain broken")
    extra = json.loads((in_dir / "prices.json").read_text()) if (in_dir / "prices.json").exists() else {}
    stats = (json.loads((repo / "stats.json").read_text()).get("advice") if (repo / "stats.json").exists() else None) or {}
    te = json.loads((repo / "trade_engine" / "state.json").read_text()) if (repo / "trade_engine" / "state.json").exists() else None
    adv = latest_advice(repo / "ledger.jsonl")
    lines = chain_lines(repo)
    last_sig = {}
    for e in lines:
        last_sig[e["data"]["asset"]] = e["data"]["signature"]
    states = {}
    for a in ASSETS:
        s = build(a, adv.get(a), stats, last_price(repo, a, extra), te, now)
        s["signature"] = signature(s)
        states[a] = s
        if last_sig.get(a) != s["signature"]:
            prev = lines[-1]["hash"] if lines else "0" * 64
            e = {"seq": len(lines) + 1, "kind": "STATE", "recorded_at": iso(now), "schema": SCHEMA,
                 "data": {k: s[k] for k in ("asset", "signature", "signal", "actions", "view", "gates")}, "prev": prev}
            e["hash"] = hashlib.sha256((prev + canon({k: v for k, v in e.items() if k != "hash"})).encode()).hexdigest()
            lines.append(e)
            (repo / "decision").mkdir(exist_ok=True)
            with (repo / "decision" / "states.jsonl").open("a") as fh:
                fh.write(canon(e) + "\n")
    out = {"schema": SCHEMA, "updated_at": iso(now), "assets": states}
    (repo / "decision").mkdir(exist_ok=True)
    (repo / "decision" / "state.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


def fetch(out_dir: Path) -> None:
    out = {}
    try:
        with urllib.request.urlopen(urllib.request.Request(KLINES, headers={"User-Agent": "ai-quant-ledger"}), timeout=20) as r:
            k = json.loads(r.read().decode())
        closed = [x for x in k if int(x[6]) < datetime.now(timezone.utc).timestamp() * 1000]
        if closed:
            out["PAXG"] = {"value": float(closed[-1][4]), "at": iso(datetime.fromtimestamp((int(closed[-1][6]) + 1) / 1000, timezone.utc))}
    except Exception as e:  # noqa: BLE001
        print("decision fetch: PAXG unavailable:", type(e).__name__)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prices.json").write_text(json.dumps(out))


def main(argv: list) -> int:
    if len(argv) >= 3 and argv[1] == "fetch":
        fetch(Path(argv[2]))
        return 0
    if len(argv) >= 3 and argv[1] == "apply":
        try:
            o = apply(Path(argv[2]), Path(argv[3] if len(argv) > 3 else "."))
            print("decision state:", {a: (s["actions"]["holder"]["action"], s["actions"]["cash"]["action"]) for a, s in o["assets"].items()})
        except Exception as e:  # noqa: BLE001  (never blocks the range ledger)
            print("decision state failed:", e)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
