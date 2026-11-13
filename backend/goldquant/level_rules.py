"""How support/resistance levels act inside the decision (see docs/adr/ADR-006-levels-in-decision.md).

Asymmetric by design: an UNVALIDATED strength label may only make the system MORE cautious (veto, contrary
evidence, better entry). Levels can SUPPORT a trade only when the strength model passed out-of-sample validation.
Levels never create a trade on their own.
"""
from __future__ import annotations

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
                e.vetoes.append(f"مقاومة قوية {z['name']} عند {z['price']:.2f} قبل الهدف — العائد المتوقع غير مناسب")
                break
        else:
            if blockers:
                z = blockers[0]
                e.contrary.append(Evidence(engine="levels", weight=-0.3,
                                           text_ar=f"مقاومة {z['name']} ({z['price']:.2f}) قبل الهدف قد تحد من الصعود"))
        if stop is not None:
            inside = [z for z in sups if z["zone_low"] <= stop <= z["zone_high"]]
            if inside:
                e.contrary.append(Evidence(engine="levels", weight=-0.3, text_ar=(
                    f"الوقف داخل منطقة الدعم {inside[0]['name']} — عرضة للضرب بسحب سيولة؛ الأفضل خلف المنطقة")))
            guard = [z for z in sups if z["zone_low"] > stop]
            if guard and validated and is_strong(guard[0]):
                e.support.append(Evidence(engine="levels", weight=0.3,
                                          text_ar=f"دعم قوي {guard[0]['name']} ({guard[0]['price']:.2f}) يحمي الوقف"))
        if s1 and atr and (price - s1["zone_high"]) <= 1.5 * atr and s1.get("strength_label_ar") != "ضعيف":
            e.better_entry = round(s1["zone_high"], 2)
        if s1:
            e.reevaluate_ar.append(f"ارتداد نحو {s1['name']} قرب {s1['zone_high']:.2f} مع ثبات فوقه")
        if r1:
            e.reevaluate_ar.append(f"إغلاق ساعة فوق {r1['name']} عند {r1['zone_high']:.2f}")
    elif direction < 0:
        blockers = [z for z in sups if target is not None and z["zone_high"] > target]
        for z in blockers:
            if is_strong(z):
                e.vetoes.append(f"دعم قوي {z['name']} عند {z['price']:.2f} قبل الهدف — العائد المتوقع غير مناسب")
                break
        else:
            if blockers:
                z = blockers[0]
                e.contrary.append(Evidence(engine="levels", weight=-0.3,
                                           text_ar=f"دعم {z['name']} ({z['price']:.2f}) قبل الهدف قد يحد من الهبوط"))
        if stop is not None:
            inside = [z for z in ress if z["zone_low"] <= stop <= z["zone_high"]]
            if inside:
                e.contrary.append(Evidence(engine="levels", weight=-0.3, text_ar=(
                    f"الوقف داخل منطقة المقاومة {inside[0]['name']} — عرضة للضرب بسحب سيولة؛ الأفضل خلف المنطقة")))
            guard = [z for z in ress if z["zone_high"] < stop]
            if guard and validated and is_strong(guard[0]):
                e.support.append(Evidence(engine="levels", weight=0.3,
                                          text_ar=f"مقاومة قوية {guard[0]['name']} ({guard[0]['price']:.2f}) تحمي الوقف"))
        if r1 and atr and (r1["zone_low"] - price) <= 1.5 * atr and r1.get("strength_label_ar") != "ضعيف":
            e.better_entry = round(r1["zone_low"], 2)
        if r1:
            e.reevaluate_ar.append(f"ارتداد نحو {r1['name']} قرب {r1['zone_low']:.2f} مع فشل في تجاوزه")
        if s1:
            e.reevaluate_ar.append(f"إغلاق ساعة تحت {s1['name']} عند {s1['zone_low']:.2f}")
    else:
        if s1 and r1:
            e.reevaluate_ar.append(f"إغلاق ساعة فوق {r1['price']:.2f} أو تحت {s1['price']:.2f} لتحديد الاتجاه")
    return e
