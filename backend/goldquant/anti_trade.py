"""Anti-Trade Engine (V2 #18): an independent gate whose only job is to reject low-quality trades.

It never proposes a trade. It receives the candidate and every other engine's output and returns the list
of rejection reasons. An empty list is required (but not sufficient) for BUY/SELL. WAIT is the default.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TradeCandidate:
    direction: int
    mode_live: bool
    data_fresh: bool
    vol_regime: str  # STRONG_TREND | RANGE | HIGH_VOL | EXCEPTIONAL
    critic_vetoes: list = field(default_factory=list)
    path_qualified: bool = False
    path_reason_ar: str = ""
    p_tp: Optional[float] = None
    p_sl: Optional[float] = None
    expected_net_return: Optional[float] = None
    min_edge_usd: float = 0.10
    drift_alarm: bool = False
    drift_reasons_ar: list = field(default_factory=list)
    news_calendar_connected: bool = False
    duplicate_active_signal: bool = False
    uncertainty_level: str = "HIGH"  # LOW | MEDIUM | HIGH


def evaluate(c: TradeCandidate) -> list[str]:
    r: list[str] = []
    if c.direction == 0:
        r.append("لا يوجد انحياز واضح متوافق بين الأطر الزمنية")
    if not c.data_fresh:
        r.append("البيانات ليست حديثة")
    if c.vol_regime == "EXCEPTIONAL":
        r.append("ظروف سوق استثنائية — لا ثقة في النماذج")
    r.extend(c.critic_vetoes)
    if not c.path_qualified:
        r.append(f"نموذج الاحتمالات غير مؤهل: {c.path_reason_ar}")
    elif c.expected_net_return is None or c.expected_net_return < c.min_edge_usd:
        r.append("العائد المتوقع بعد السبريد والانزلاق غير كافٍ")
    if c.p_tp is not None and c.p_sl is not None and c.p_sl >= c.p_tp:
        r.append("احتمال ضرب الوقف أولاً لا يقل عن احتمال بلوغ الهدف")
    if c.drift_alarm:
        r.extend(c.drift_reasons_ar or ["إنذار انحراف النموذج"])
    if c.mode_live and not c.news_calendar_connected:
        r.append("لا تُصدر إشارات حية قبل ربط تقويم الأخبار (حماية من الأخبار المفاجئة)")
    if c.duplicate_active_signal:
        r.append("توجد إشارة مماثلة سابقة ما زالت سارية — منع التكرار")
    if c.uncertainty_level == "HIGH" and c.path_qualified:
        r.append("عدم اليقين الكلي مرتفع")
    return r
