"""advice-0.1.0 — the app's «ماذا أفعل؟» instruction, recorded and scored in the public ledger.

PRE-REGISTERED 2026-11-17 (owner-approved), before any advice outcome exists. Nothing below changes after results
are seen; a change is a new version recorded next to this one.

What is recorded (once per asset per UTC day, at the first fresh snapshot of the day, kind ADVICE):
  the HOURS and WEEK views exactly as the app builds them (HorizonScenarios.kt), and the instruction for a
  HOLDER and for CASH (decide below, mirror of HorizonScenarios.decide).

How it is scored (window = the 168 hours after recording, closed H1 bars only, no look-ahead):
  costs: `cost` from the snapshot is one round trip in price units; one trade = cost / 2.
  a limit fills at its level, or at the bar open when the bar opens beyond it (better fill);
  an exit (stop) fills at its level, or at the bar open when it gaps beyond it (worse fill);
  a bar touching both the order and the exit counts as the exit (the worse case).
  HOLDER, measured against simply holding to the end of the window (excess, % of the recording price):
    SELL_NOW (buy back at `at`, exit = buy back above `exit`): (p0 − rebuy − cost) / p0;
             never bought back: (p0 − close_end − cost/2) / p0
    KEEP_SELL_HIGHER (sell at `at`, exit = sell below `exit`): (sell − close_end − cost/2) / p0; neither: 0
    NOTHING: 0
  CASH, measured as the return of the instruction (% of the recording price), staying in cash = 0:
    WAIT_BUY_LOWER (buy at `at`, exit = buy above `exit`): (close_end − fill − cost) / p0; never filled: 0
    BUY_NOW (exit = sell below `exit`): (exit_or_close_end − p0 − cost) / p0
    DONT_BUY, NOTHING: 0;  every CASH row also carries buy-now-and-hold as a reference.
Verdict per asset and instruction (shown only with n >= 20 settled rows; daily rows overlap, so they are not
independent — the count of non-overlapping weeks is reported next to n):
  holder instruction PASSES when its mean excess > 0 AND it beat holding in >= 50 % of rows;
  WAIT_BUY_LOWER / BUY_NOW PASS when the mean return > 0 AND the mean beats buy-now-and-hold;
  DONT_BUY PASSES when buy-now-and-hold had a mean return <= 0 over its rows.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

VERSION = "advice-0.1.0"
WINDOW = timedelta(hours=168)
MIN_N = 20


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.011, abs(b) * 1e-7)


def view(snap: dict, horizon: str) -> Optional[dict]:
    """{down: [trigger, target|None]|None, up: ..., likely: DOWN|UP|BETWEEN|NONE} or None (no such horizon)."""
    o = {x.get("horizon"): x for x in snap.get("outlooks") or []}.get(horizon)
    if o is None:
        return None
    down = up = None
    b = snap.get("brief") or {}
    if horizon == "HOURS" and b:
        for sc in b.get("scenarios") or []:
            if sc.get("kind") == "BEAR" and down is None:
                down = [float(sc["trigger"]), None if sc.get("target") is None else float(sc["target"])]
            if sc.get("kind") == "BULL" and up is None:
                up = [float(sc["trigger"]), None if sc.get("target") is None else float(sc["target"])]
    sup, res = o.get("supports") or [], o.get("resistances") or []
    if down is None and sup:
        down = [float(sup[0]), float(sup[1]) if len(sup) > 1 else None]
    if up is None and res:
        up = [float(res[0]), float(res[1]) if len(res) > 1 else None]
    action = snap.get("action") if horizon == "HOURS" else o.get("action")
    side = o.get("plan_side") if snap.get("mode", "LIVE") == "LIVE" else None
    likely = "NONE"
    o3 = b.get("outcome3") if horizon == "HOURS" else None
    o3l = None
    if o3 and down and up and _same(float(o3["down_level"]), down[0]) and _same(float(o3["up_level"]), up[0]):
        o3l = {"DOWN": "DOWN", "UP": "UP", "NONE": "BETWEEN"}.get(o3.get("likely"))
    if side == "SELL":
        likely = "DOWN"
    elif side == "BUY":
        likely = "UP"
    elif o3l:
        likely = o3l
    elif action == "SELL":
        likely = "DOWN"
    elif action == "BUY":
        likely = "UP"
    ok = {"DOWN": down is not None, "UP": up is not None, "BETWEEN": down is not None and up is not None}.get(likely, True)
    return {"down": down, "up": up, "likely": likely if ok else "NONE"}


def _dir(v):
    return {"DOWN": -1, "UP": 1}.get((v or {}).get("likely"), 0)


def _at(side):
    return None if side is None else (side[1] if side[1] is not None else side[0])


def decide(hours: Optional[dict], week: Optional[dict], hold: bool) -> dict:
    h, w = _dir(hours), _dir(week)
    if h == -1 and w == 1:
        return {"advice": "SELL_NOW" if hold else "WAIT_BUY_LOWER", "at": _at(hours["down"]),
                "exit": hours["up"][0] if hours["up"] else None, "mix": "DIP_IN_UPTREND", "basis": "HOURS"}
    if h == 1 and w == -1:
        if hold:
            return {"advice": "KEEP_SELL_HIGHER", "at": _at(hours["up"]),
                    "exit": hours["down"][0] if hours["down"] else None, "mix": "BOUNCE_IN_DOWNTREND", "basis": "HOURS"}
        return {"advice": "DONT_BUY", "at": None, "exit": None, "mix": "BOUNCE_IN_DOWNTREND", "basis": "HOURS"}
    if h:
        v, basis = hours, "HOURS"
    elif w:
        v, basis = week, "WEEK"
    else:
        return {"advice": "NOTHING", "at": None, "exit": None, "mix": None, "basis": None}
    if _dir(v) == -1:
        return {"advice": "SELL_NOW" if hold else "WAIT_BUY_LOWER", "at": _at(v["down"]),
                "exit": v["up"][0] if v["up"] else None, "mix": None, "basis": basis}
    return {"advice": "KEEP_SELL_HIGHER" if hold else "BUY_NOW", "at": _at(v["up"]) if hold else None,
            "exit": v["down"][0] if v["down"] else None, "mix": None, "basis": basis}


def record(snap: dict) -> Optional[dict]:
    """The ADVICE payload for this snapshot, or None when the snapshot predates the advice inputs."""
    if not snap.get("outlooks"):
        return None
    hours, week = view(snap, "HOURS"), view(snap, "WEEK")
    return {"version": VERSION, "hours": hours, "week": week,
            "hold": decide(hours, week, True), "cash": decide(hours, week, False)}


# ---------------------------------------------------------------- scoring
def _first(window, lo: Optional[float], hi: Optional[float]):
    """First bar touching lo (low <= lo) or hi (high >= hi): ('lo'|'hi', bar). Both in one bar → caller decides."""
    for b in window:
        tl = lo is not None and b[3] <= lo
        th = hi is not None and b[2] >= hi
        if tl or th:
            return ("both" if tl and th else "lo" if tl else "hi"), b
    return None, None


def score(a: dict, p0: float, cost: float, window: list) -> dict:
    """window = closed H1 bars (t, o, h, l, c) of the 168 hours after recording, oldest first (non-empty)."""
    end = window[-1][4]
    pct = lambda x: round(x / p0 * 100, 4)  # noqa: E731
    out = {"close_end": end, "ref_buy_hold_pct": pct(end - p0 - cost)}
    hold, cash = a["hold"], a["cash"]
    # ---- holder
    adv, at, ex = hold["advice"], hold["at"], hold["exit"]
    if adv == "SELL_NOW":
        how, b = _first(window, at, ex)  # buy back at `at` (below) or above `exit`
        if how is None:
            out["hold"] = {"how": "NOT_BOUGHT_BACK", "excess_pct": pct(p0 - end - cost / 2)}
        else:
            px = max(ex, b[1]) if how in ("hi", "both") else min(at, b[1])
            out["hold"] = {"how": "EXIT" if how in ("hi", "both") else "BOUGHT_BACK", "price": px,
                           "excess_pct": pct(p0 - px - cost)}
    elif adv == "KEEP_SELL_HIGHER":
        how, b = _first(window, ex, at)  # sell below `exit` or at `at` (above)
        if how is None:
            out["hold"] = {"how": "HELD", "excess_pct": 0.0}
        else:
            px = min(ex, b[1]) if how in ("lo", "both") else max(at, b[1])
            out["hold"] = {"how": "EXIT" if how in ("lo", "both") else "SOLD", "price": px,
                           "excess_pct": pct(px - end - cost / 2)}
    else:
        out["hold"] = {"how": "NOTHING", "excess_pct": 0.0}
    # ---- cash
    adv, at, ex = cash["advice"], cash["at"], cash["exit"]
    if adv == "WAIT_BUY_LOWER":
        how, b = _first(window, at, ex)
        if how is None:
            out["cash"] = {"how": "NOT_FILLED", "return_pct": 0.0}
        else:
            px = max(ex, b[1]) if how in ("hi", "both") else min(at, b[1])
            out["cash"] = {"how": "EXIT_BUY" if how in ("hi", "both") else "FILLED", "price": px,
                           "return_pct": pct(end - px - cost)}
    elif adv == "BUY_NOW":
        how, b = _first(window, ex, None)
        px = end if how is None else min(ex, b[1])
        out["cash"] = {"how": "HELD" if how is None else "EXIT", "price": px, "return_pct": pct(px - p0 - cost)}
    else:
        out["cash"] = {"how": adv, "return_pct": 0.0}
    return out


def stats(rows: list[dict]) -> dict:
    """rows: settled ADVICE results [{asset, date, hold_advice, cash_advice, mix, result}]. Per asset × instruction."""
    out: dict = {"version": VERSION, "min_n": MIN_N, "assets": {}}
    for r in rows:
        A = out["assets"].setdefault(r["asset"], {"hold": {}, "cash": {}})
        for side, adv, val, ref in (("hold", r["hold_advice"], r["result"]["hold"]["excess_pct"], None),
                                    ("cash", r["cash_advice"], r["result"]["cash"]["return_pct"],
                                     r["result"]["ref_buy_hold_pct"])):
            c = A[side].setdefault(adv, {"n": 0, "sum": 0.0, "wins": 0, "ref_sum": 0.0, "days": []})
            c["n"] += 1
            c["sum"] += val
            c["wins"] += 1 if val > 0 else 0
            c["ref_sum"] += ref or 0.0
            c["days"].append(r["date"])
    for A in out["assets"].values():
        for side in ("hold", "cash"):
            for adv, c in A[side].items():
                n = c["n"]
                days = sorted(datetime.fromisoformat(d) for d in c.pop("days"))
                weeks, last = 0, None
                for d in days:  # non-overlapping 7-day windows
                    if last is None or d - last >= timedelta(days=7):
                        weeks, last = weeks + 1, d
                c["weeks"] = weeks
                c["mean"] = round(c.pop("sum") / n, 4)
                ref = round(c.pop("ref_sum") / n, 4)
                c["win_rate"] = round(c["wins"] / n, 4)
                if side == "cash":
                    c["ref_buy_hold_mean"] = ref
                verdict = None
                if n >= MIN_N:
                    if side == "hold" and adv != "NOTHING":
                        verdict = c["mean"] > 0 and c["win_rate"] >= 0.5
                    elif adv in ("WAIT_BUY_LOWER", "BUY_NOW"):
                        verdict = c["mean"] > 0 and c["mean"] > ref
                    elif adv == "DONT_BUY":
                        verdict = ref <= 0
                c["verdict"] = None if verdict is None else ("PASS" if verdict else "FAIL")
    return out
