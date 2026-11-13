"""Risk engine: invalidation-based stop, targets in R multiples, explicit cost estimate."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Estimated (NOT measured) retail costs for XAU/USD in USD per ounce. Documented as estimates.
EST_SPREAD = 0.35
EST_SLIPPAGE = 0.10
TARGET_R = (1.0, 1.8, 2.8)


@dataclass
class Levels:
    entry_min: float
    entry_max: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    risk_per_oz: float
    cost_per_oz: float
    reward_risk_tp1: float


def estimated_cost() -> float:
    return EST_SPREAD + EST_SLIPPAGE


def breakeven_probability(risk: float, reward: float, cost: float) -> float:
    """p such that p*(reward-cost) - (1-p)*(risk+cost) = 0 (timeouts treated as losses: conservative)."""
    return (risk + cost) / (reward + risk)


def compute_levels(direction: int, price: float, atr15: float, stop_atr: float = 2.0) -> Optional[Levels]:
    """Stop distance matches the model's barrier definition (stop_atr * ATR(M15)) so that any
    probability estimate refers to exactly these levels."""
    if atr15 <= 0 or price <= 0:
        return None
    cost = estimated_cost()
    half_band = 0.15 * atr15
    risk = stop_atr * atr15
    entry_min, entry_max = price - half_band, price + half_band
    if direction > 0:
        sl = price - risk
        tps = [price + r * risk for r in TARGET_R]
    else:
        sl = price + risk
        tps = [price - r * risk for r in TARGET_R]
    r2 = lambda x: round(x, 2)  # noqa: E731
    return Levels(r2(entry_min), r2(entry_max), r2(sl), r2(tps[0]), r2(tps[1]), r2(tps[2]),
                  risk_per_oz=round(risk, 2), cost_per_oz=cost, reward_risk_tp1=TARGET_R[0])


def stop_inside_structure(direction: int, stop: float, swing_low: float, swing_high: float) -> bool:
    """True when the stop sits INSIDE recent structure (a normal swing could hit it)."""
    return stop > swing_low if direction > 0 else stop < swing_high
