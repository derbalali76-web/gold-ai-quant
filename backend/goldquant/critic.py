"""Adversarial critic: collects contrary evidence and hard vetoes independent of the signal's own logic."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .regime import Regime
from .schemas import Evidence


@dataclass
class CriticResult:
    contrary: list[Evidence] = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)
    wait_for_ar: str | None = None
    wait_for_price: float | None = None


def review(direction: int, m15_row: pd.Series, h4_row: pd.Series, regime: Regime, session: str,
           stop_inside_structure: bool, minutes_to_weekly_close: float | None) -> CriticResult:
    out = CriticResult()
    if direction == 0:
        return out
    side_ar = "الشراء" if direction > 0 else "البيع"

    if regime.vol == "EXTREME":
        out.vetoes.append("تقلب حاد غير طبيعي — النماذج غير موثوقة في هذه الظروف")
    if abs(m15_row.get("ret_z", 0.0)) > 4.5:
        out.vetoes.append("شمعة شاذة إحصائياً (robust z > 4.5) — احتمال خبر أو فجوة سعرية")
    if regime.trend == "RANGE":
        out.contrary.append(Evidence(engine="regime", weight=-0.5,
                                     text_ar=f"السوق في تذبذب عرضي؛ إشارات الاتجاه ضعيفة الموثوقية"))
    h4_slope = float(h4_row.get("slope_ema50_atr", 0.0))
    if h4_slope * direction < -0.1:
        out.contrary.append(Evidence(engine="mtf", weight=-0.6, text_ar=f"اتجاه H4 يعاكس {side_ar}"))
    dist = float(m15_row.get("dist_ema20_atr", 0.0)) * direction
    if dist > 2.0:
        target = float(m15_row["ema20"]) + direction * 0.5 * float(m15_row["atr"])
        out.vetoes.append("السعر ممتد بعيداً عن متوسطه (> 2 ATR) — مطاردة السعر هنا ضعيفة")
        out.wait_for_price = round(target, 2)
        out.wait_for_ar = f"انتظر ارتداداً نحو {target:.2f} قبل التفكير في {side_ar}"
    if stop_inside_structure:
        out.contrary.append(Evidence(engine="liquidity_proxy", weight=-0.3,
                                     text_ar="وقف الخسارة يقع داخل نطاق آخر قمة/قاع (استدلال من شكل السعر)"))
    if session in ("ASIA",):
        out.contrary.append(Evidence(engine="session", weight=-0.2, text_ar="جلسة آسيا: سيولة أقل وحركة أبطأ عادةً"))
    if session in ("CLOSED", "DAILY_BREAK"):
        out.vetoes.append("السوق مغلق أو في استراحة يومية")
    if minutes_to_weekly_close is not None and minutes_to_weekly_close < 240:
        out.vetoes.append("أقل من 4 ساعات على إغلاق الأسبوع — خطر فجوة نهاية الأسبوع")
    if regime.bars_since_break == regime.bars_since_break and regime.bars_since_break < 4:
        out.contrary.append(Evidence(engine="change_point", weight=-0.4,
                                     text_ar="كُشف تغيّر هيكلي حديث في سلوك السعر (CUSUM)"))
    return out
