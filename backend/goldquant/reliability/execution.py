"""Execution Reality Simulator (V4 #6): session/volatility-dependent spread, volatility-scaled slippage,
random latency (which can push the fill one bar later) and missed limit fills.

All parameters are ESTIMATES for retail XAU/USD (no free source publishes real spreads); they are deliberately
on the pessimistic side and reported with every result.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SESSION_SPREAD = {"ASIA": 0.45, "LONDON": 0.30, "LONDON_NY_OVERLAP": 0.25, "NEW_YORK": 0.30,
                  "DAILY_BREAK": 1.20, "CLOSED": 2.00}


@dataclass
class ExecutionModel:
    slippage_base: float = 0.05
    slippage_atr_frac: float = 0.04
    latency_mean_s: float = 20.0  # phone -> human -> broker
    late_bar_threshold_s: float = 60.0
    limit_queue_buffer_frac: float = 0.5  # price must trade THROUGH a limit by this share of the spread
    seed: int = 11

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)

    def spread(self, session: str, vol_ratio: float) -> float:
        base = SESSION_SPREAD.get(session, 0.40)
        vr = vol_ratio if vol_ratio == vol_ratio else 1.0
        return base * (1.0 + max(0.0, vr - 1.0))

    def slippage(self, atr15: float) -> float:
        return self.slippage_base + abs(self.rng.normal(0, 1)) * self.slippage_atr_frac * atr15

    def entry_delay_bars(self) -> int:
        lat = self.rng.exponential(self.latency_mean_s)
        return 2 if lat > self.late_bar_threshold_s else 1

    def limit_filled(self, direction: int, limit: float, bar_low: float, bar_high: float, spread: float) -> bool:
        buf = self.limit_queue_buffer_frac * spread
        return bar_low <= limit - buf if direction > 0 else bar_high >= limit + buf

    def describe(self) -> dict:
        return {"spread_by_session": SESSION_SPREAD, "slippage": f"{self.slippage_base} + |N|×{self.slippage_atr_frac}×ATR15",
                "latency_mean_s": self.latency_mean_s, "late_bar_threshold_s": self.late_bar_threshold_s,
                "note_ar": "معاملات تقديرية متحفظة — لا يوجد مصدر مجاني لفروقات الأسعار الحقيقية"}
