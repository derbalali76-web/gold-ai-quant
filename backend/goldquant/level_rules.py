"""How support/resistance levels act inside the decision (see docs/adr/ADR-006-levels-in-decision.md).

Asymmetric by design: an UNVALIDATED strength label may only make the system MORE cautious (veto, contrary
evidence, better entry). Levels can SUPPORT a trade only when the strength model passed out-of-sample validation.
Levels never create a trade on their own.
"""
from __future__ import annotations
from .msg import M

from dataclasses import dataclass, field

from .schemas import Evidence

STRONG_PCT = 67


def is_strong(z: dict) -> bool:
    return (z.get("strength") is not None and z["strength"] >= STRONG_PCT) or z.get("strength_label_ar") == "قوي"


@dataclass
class LevelEffect:
    vetoes: list = field(default_factory=list)
    support: list = field(default_factory=list)
    contrary: list = field(default_factory=list)
    better_entry: float | None = None
    reevaluate_ar: list = field(default_factory=list)


def apply(direction: int, price: float, stop: float | None, target: float | None, sr: dict) -> LevelEffect:
    e = LevelEffect()
    sups, ress = sr.get("supports", []), sr.get("resistances", [])
    validated = bool(sr.get("validated"))
    atr = sr.get("atr_h1") or 0.0
    s1, r1 = (sups[0] if sups else None), (ress[0] if ress else None)
    if direction > 0:
        blockers = [z for z in ress if target is not None and z["zone_low"] < target]
        for z in blockers:
            if is_strong(z):
                e.vetoes.append(M("lv.strong_res", z["name"], f"{z['price']:.2f}"))
                break
        else:
            if blockers:
                z = blockers[0]
                e.contrary.append(Evidence(engine="levels", weight=-0.3,
                                           text_ar=M("ev.lv_res_before", z["name"], f"{z['price']:.2f}")))
        if stop is not None:
            inside = [z for z in sups if z["zone_low"] <= stop <= z["zone_high"]]
            if inside:
                e.contrary.append(Evidence(engine="levels", weight=-0.3, text_ar=M("ev.lv_stop_in_sup", inside[0]["name"])))
            guard = [z for z in sups if z["zone_low"] > stop]
            if guard and validated and is_strong(guard[0]):
                e.support.append(Evidence(engine="levels", weight=0.3,
                                          text_ar=M("ev.lv_sup_guard", guard[0]["name"], f"{guard[0]['price']:.2f}")))
        if s1 and atr and (price - s1["zone_high"]) <= 1.5 * atr and s1.get("strength_label_ar") != "ضعيف":
            e.better_entry = round(s1["zone_high"], 2)
        if s1:
            e.reevaluate_ar.append(M("rv.bounce_sup", s1["name"], f"{s1['zone_high']:.2f}"))
        if r1:
            e.reevaluate_ar.append(M("rv.close_above", r1["name"], f"{r1['zone_high']:.2f}"))
    elif direction < 0:
        blockers = [z for z in sups if target is not None and z["zone_high"] > target]
        for z in blockers:
            if is_strong(z):
                e.vetoes.append(M("lv.strong_sup", z["name"], f"{z['price']:.2f}"))
                break
        else:
            if blockers:
                z = blockers[0]
                e.contrary.append(Evidence(engine="levels", weight=-0.3,
                                           text_ar=M("ev.lv_sup_before", z["name"], f"{z['price']:.2f}")))
        if stop is not None:
            inside = [z for z in ress if z["zone_low"] <= stop <= z["zone_high"]]
            if inside:
                e.contrary.append(Evidence(engine="levels", weight=-0.3, text_ar=M("ev.lv_stop_in_res", inside[0]["name"])))
            guard = [z for z in ress if z["zone_high"] < stop]
            if guard and validated and is_strong(guard[0]):
                e.support.append(Evidence(engine="levels", weight=0.3,
                                          text_ar=M("ev.lv_res_guard", guard[0]["name"], f"{guard[0]['price']:.2f}")))
        if r1 and atr and (r1["zone_low"] - price) <= 1.5 * atr and r1.get("strength_label_ar") != "ضعيف":
            e.better_entry = round(r1["zone_low"], 2)
        if r1:
            e.reevaluate_ar.append(M("rv.bounce_res", r1["name"], f"{r1['zone_low']:.2f}"))
        if s1:
            e.reevaluate_ar.append(M("rv.close_below", s1["name"], f"{s1['zone_low']:.2f}"))
    else:
        if s1 and r1:
            e.reevaluate_ar.append(M("rv.break_either", f"{r1['price']:.2f}", f"{s1['price']:.2f}"))
    return e
