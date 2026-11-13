"""Independent Risk Governor (V4 #2).

It does not look at signals' reasoning — only at the proposed trade's risk geometry, current market state and
the paper-trading ledger — and it can veto anything. Limits are deliberately conservative (simulation only).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class GovernorLimits:
    max_signals_per_day: int = 4
    max_open_positions: int = 1
    daily_loss_limit_r: float = -2.0
    max_consecutive_losses: int = 3
    cooldown: timedelta = timedelta(hours=4)
    min_reward_risk: float = 1.0
    min_stop_atr15: float = 1.0
    max_stop_atr15: float = 5.0
    max_cost_to_risk: float = 0.25


@dataclass
class GovernorVerdict:
    approved: bool
    reasons_ar: list = field(default_factory=list)
    state: dict = field(default_factory=dict)


def review(direction: int, risk_per_oz: float | None, reward_risk: float | None, cost: float, atr15: float,
           vol_regime: str, quote_age_s: float | None, max_quote_age_s: float, ledger_state: dict,
           limits: GovernorLimits | None = None, now: datetime | None = None) -> GovernorVerdict:
    L = limits or GovernorLimits()
    r: list[str] = []
    if direction == 0 or risk_per_oz is None:
        return GovernorVerdict(False, ["لا توجد صفقة مقترحة"], ledger_state)
    if quote_age_s is None or quote_age_s > max_quote_age_s:
        r.append("السعر غير حديث")
    if vol_regime == "EXCEPTIONAL":
        r.append("ظروف سوق استثنائية")
    if reward_risk is None or reward_risk < L.min_reward_risk:
        r.append(f"نسبة العائد/المخاطرة أقل من {L.min_reward_risk}")
    k = risk_per_oz / atr15 if atr15 > 0 else float("inf")
    if not (L.min_stop_atr15 <= k <= L.max_stop_atr15):
        r.append(f"مسافة الوقف {k:.1f}×ATR خارج الحدود المسموحة")
    if risk_per_oz > 0 and cost / risk_per_oz > L.max_cost_to_risk:
        r.append("التكاليف تلتهم جزءاً كبيراً من المخاطرة (السبريد واسع نسبياً)")
    st = ledger_state or {}
    if st.get("signals_24h", 0) >= L.max_signals_per_day:
        r.append(f"بلغ الحد الأقصى للإشارات اليومية ({L.max_signals_per_day})")
    if st.get("open_positions", 0) >= L.max_open_positions:
        r.append("توجد صفقة ورقية مفتوحة بالفعل")
    if st.get("pnl_r_24h", 0.0) <= L.daily_loss_limit_r:
        r.append("تجاوز حد الخسارة اليومي في التداول الورقي")
    if st.get("consecutive_losses", 0) >= L.max_consecutive_losses and now is not None and st.get("last_loss_at"):
        if now - st["last_loss_at"] < L.cooldown:
            r.append(f"فترة تهدئة بعد {st['consecutive_losses']} خسائر متتالية")
    return GovernorVerdict(not r, r, {k2: (v.isoformat() if hasattr(v, "isoformat") else v) for k2, v in st.items()})
