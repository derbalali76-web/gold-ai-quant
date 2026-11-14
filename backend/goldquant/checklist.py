"""Live entry checklist (v1.7.3): what must be true before a horizon may trade, and which conditions are met now.
Built only from facts the engine already has; it never relaxes a gate and never creates a trade."""
from __future__ import annotations

from .schemas import Check, Decision, HorizonOutlook

NEAR_ATR = 0.5  # "at a level": within half an ATR of the nearest support / resistance
MIN_RR = 1.5


def _nearest(levels, price: float):
    best = None
    for l in list(levels.supports) + list(levels.resistances):
        if best is None or abs(l.price - price) < abs(best.price - price):
            best = l
    return best


def build(d: Decision, o: HorizonOutlook, ctx=None) -> list[Check]:
    out = [Check(code="session", ok=not d.market_closed)]
    if ctx is not None and getattr(ctx, "calendar_connected", False):
        ev = list(getattr(ctx, "embargo_events", []) or [])
        name = str(ev[0].get("name") if isinstance(ev[0], dict) else ev[0])[:40] if ev else ""
        out.append(Check(code="news", ok=not ev, args=[name] if ev else []))
    else:
        out.append(Check(code="news", ok=None))
    if o.horizon == "HOURS":
        out.append(Check(code="volatility", ok=None if d.vol_regime is None else d.vol_regime not in ("HIGH_VOL", "EXCEPTIONAL")))
        t = d.market_trend
        out.append(Check(code="trend", ok=None if t is None else bool(t.direction in ("UP", "DOWN") and (t.agreement or 0) >= 0.67)))
        lv = d.levels
    else:
        t = o.trend
        out.append(Check(code="trend", ok=None if t is None else bool(t.direction in ("UP", "DOWN") and (t.strength or 0) >= 50)))
        lv = o.levels
    if lv is not None and d.quote is not None and (lv.supports or lv.resistances):
        n = _nearest(lv, float(d.quote))
        out.append(Check(code="level", ok=abs(n.distance_atr) <= NEAR_ATR,
                         args=[n.name, f"{abs(n.price - float(d.quote)):.2f}"]))
    else:
        out.append(Check(code="level", ok=None))
    p = o.plan
    if p is not None and p.reward_risk is not None and p.stop_loss is not None:
        out.append(Check(code="reward_risk", ok=p.reward_risk >= MIN_RR, args=[f"{p.reward_risk:.2f}"]))
    out.append(Check(code="model", ok=bool(o.validated)))
    return out


def attach(d: Decision, ctx=None) -> None:
    for o in d.outlooks:
        o.checklist = build(d, o, ctx)
