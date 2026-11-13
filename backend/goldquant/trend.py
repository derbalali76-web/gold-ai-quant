"""Market Trend Engine: overall direction (up / down / sideways) and a 0-100 trend-strength SCORE.

Per timeframe (M15, M30, H1, H4): slope of EMA50 in ATR units, position vs EMA20 and efficiency ratio.
Combined with weights H4 .35, H1 .30, M30 .20, M15 .15, multiplied by the agreement between timeframes
(conflict lowers the score) and damped in high / exceptional volatility. It is an analytical score describing
the current state — NOT a probability of the trend continuing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WEIGHTS = {"H4": 0.35, "H1": 0.30, "M30": 0.20, "M15": 0.15}
SIDEWAYS_BELOW = 0.20
VOL_DAMP = {"STRONG_TREND": 1.0, "RANGE": 0.85, "HIGH_VOL": 0.8, "EXCEPTIONAL": 0.5}


def tf_score(row: pd.Series) -> float:
    slope = float(np.clip(row.get("slope_ema50_atr", 0.0) / 0.6, -1, 1))
    pos = float(np.clip(row.get("dist_ema20_atr", 0.0) / 1.5, -1, 1))
    er = float(np.clip(row.get("er20", 0.0), 0, 1))
    raw = 0.55 * slope + 0.25 * pos
    return float(np.clip(raw * (0.6 + 0.8 * er), -1, 1)) if np.isfinite(raw) else 0.0


def market_trend(last_rows: dict, vol_regime: str) -> dict:
    per = {tf: tf_score(r) for tf, r in last_rows.items() if tf in WEIGHTS}
    if not per:
        return {"direction": "UNKNOWN", "strength": None, "label_ar": "غير متاح", "per_timeframe": {}}
    w = sum(WEIGHTS[k] for k in per)
    combined = sum(WEIGHTS[k] * v for k, v in per.items()) / w
    signs = [np.sign(v) for v in per.values() if abs(v) > 0.1]
    agreement = (abs(sum(signs)) / len(signs)) if signs else 0.0
    strength = abs(combined) * (0.5 + 0.5 * agreement) * VOL_DAMP.get(vol_regime, 1.0)
    direction = "SIDEWAYS" if abs(combined) < SIDEWAYS_BELOW else ("UP" if combined > 0 else "DOWN")
    label = {"UP": "صاعد", "DOWN": "هابط", "SIDEWAYS": "عرضي"}[direction]
    tf_lbl = {k: ("صاعد" if v > 0.1 else "هابط" if v < -0.1 else "محايد") for k, v in per.items()}
    return {"direction": direction, "strength": int(round(100 * min(1.0, strength))), "label_ar": label,
            "agreement": round(float(agreement), 2), "per_timeframe": tf_lbl,
            "note_ar": "درجة تحليلية لحالة الاتجاه وليست احتمالاً لاستمراره"}
