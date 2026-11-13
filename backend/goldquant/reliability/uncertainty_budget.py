"""Uncertainty Budget (V4 #7): quantified uncertainty components, each in [0, 1], against a fixed budget.

data   : quote age share of the limit, missing critical sources, firewall warnings
model  : not qualified / failed calibration, calibration error (ECE), live drift alarm
market : regime novelty (analog distance vs typical), volatility percentile tail, recent structural break
models : disagreement between independent models (when the precision layer runs)
A trade needs total <= BUDGET and no single component at 1.0.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BUDGET = 1.6
WEIGHTS = {"data": 1.0, "model": 1.0, "market": 0.8, "disagreement": 0.6}


@dataclass
class BudgetResult:
    components: dict = field(default_factory=dict)
    used: float = 0.0
    limit: float = BUDGET
    within: bool = False
    notes_ar: list = field(default_factory=list)


def compute(quote_age_s, max_age_s, n_missing_critical: int, n_firewall_warnings: int, qualified: bool,
            calibration_passed: bool, ece: float | None, drift_alarm: bool, analog_novelty: float | None,
            vol_percentile: float | None, bars_since_break: float | None, disagreement: float | None) -> BudgetResult:
    r = BudgetResult()
    age = 1.0 if quote_age_s is None else min(1.0, max(0.0, quote_age_s / max_age_s))
    data = 1.0 if quote_age_s is None else min(1.0, 0.5 * age + 0.25 * n_missing_critical + 0.1 * n_firewall_warnings)
    model = 1.0 if not qualified else (0.6 if not calibration_passed else 0.0)
    if ece is not None:
        model = min(1.0, model + min(0.4, ece * 4))
    if drift_alarm:
        model = 1.0
    nov = 0.0 if analog_novelty is None else min(1.0, max(0.0, analog_novelty - 0.5))
    tail = 0.0 if vol_percentile is None or vol_percentile != vol_percentile else max(0.0, (vol_percentile - 0.8) * 3)
    brk = 0.3 if bars_since_break is not None and bars_since_break == bars_since_break and bars_since_break < 4 else 0.0
    market = min(1.0, nov + tail + brk)
    dis = 0.0 if disagreement is None else min(1.0, disagreement / 0.3)
    r.components = {"data": round(data, 3), "model": round(model, 3), "market": round(market, 3), "disagreement": round(dis, 3)}
    r.used = round(sum(WEIGHTS[k] * v for k, v in r.components.items()), 3)
    r.within = r.used <= BUDGET and max(r.components.values()) < 1.0
    names = {"data": "البيانات", "model": "النموذج", "market": "السوق", "disagreement": "اختلاف النماذج"}
    r.notes_ar = [f"عدم يقين {names[k]} عند الحد الأقصى" for k, v in r.components.items() if v >= 1.0]
    if r.used > BUDGET:
        r.notes_ar.append(f"تجاوزت ميزانية عدم اليقين ({r.used:.2f} > {BUDGET})")
    return r
