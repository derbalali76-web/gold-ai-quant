"""Anti-Trade Engine (V2 #18): an independent gate whose only job is to reject low-quality trades.

It never proposes a trade. It receives the candidate and every other engine's output and returns the list
of rejection reasons. An empty list is required (but not sufficient) for BUY/SELL. WAIT is the default.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .msg import M


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
    min_prob_margin: float = 0.05  # p(target first) must beat p(stop first) by a clear margin
    drift_alarm: bool = False
    drift_reasons_ar: list = field(default_factory=list)
    news_calendar_connected: bool = False
    duplicate_active_signal: bool = False
    uncertainty_level: str = "HIGH"  # LOW | MEDIUM | HIGH


def evaluate(c: TradeCandidate) -> list[str]:
    r: list[str] = []
    if c.direction == 0:
        r.append(M("at.no_bias"))
    if not c.data_fresh:
        r.append(M("at.data_stale"))
    if c.vol_regime == "EXCEPTIONAL":
        r.append(M("at.exceptional"))
    r.extend(c.critic_vetoes)
    if not c.path_qualified:
        r.append(M("at.model_unqualified", c.path_reason_ar))
    elif c.expected_net_return is None or c.expected_net_return < c.min_edge_usd:
        r.append(M("at.edge_low"))
    if c.p_tp is not None and c.p_sl is not None and c.p_sl >= c.p_tp:
        r.append(M("at.stop_first"))
    elif c.p_tp is not None and c.p_sl is not None and c.p_tp - c.p_sl < c.min_prob_margin:
        r.append(M("at.margin_small"))
    if c.drift_alarm:
        r.extend(c.drift_reasons_ar or ["إنذار انحراف النموذج"])
    if c.mode_live and not c.news_calendar_connected:
        r.append(M("at.no_calendar"))
    if c.duplicate_active_signal:
        r.append(M("at.duplicate"))
    if c.uncertainty_level == "HIGH" and c.path_qualified:
        r.append(M("at.uncertainty_high"))
    return r
