"""Counterfactual Engine (V2 #12): enter now vs wait for a better price.

From history (as-of, same direction) it measures, for a limit order placed `delta` better than the current
price: how often it would have filled within `window` bars, and how often the target was reached WITHOUT
filling (missed opportunity). Empirical frequencies with sample sizes — not a calibrated forecast.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def forward_extremes(m15: pd.DataFrame, window: int = 4) -> pd.DataFrame:
    """Per bar (indexed by CLOSE time): min low / max high over the next `window` bars, in ATR units."""
    from ..features import atr
    a = atr(m15)
    lo = pd.concat([m15["low"].shift(-k) for k in range(1, window + 1)], axis=1).min(axis=1)
    hi = pd.concat([m15["high"].shift(-k) for k in range(1, window + 1)], axis=1).max(axis=1)
    out = pd.DataFrame({"fwd_low_atr": (lo - m15["close"]) / a, "fwd_high_atr": (hi - m15["close"]) / a,
                        "atr": a}, index=m15.index + pd.Timedelta(minutes=15))
    out["known_at"] = out.index + pd.Timedelta(minutes=15 * window)
    out.iloc[-window:, :2] = np.nan
    return out


def compare(fe: pd.DataFrame, direction: int, delta_atr: float, tp_atr: float, as_of) -> dict | None:
    hist = fe[fe["known_at"] <= pd.Timestamp(as_of)].dropna()
    if len(hist) < 500 or delta_atr <= 0:
        return None
    if direction > 0:
        filled = hist["fwd_low_atr"] <= -delta_atr
        ran_away = (~filled) & (hist["fwd_high_atr"] >= tp_atr)
    else:
        filled = hist["fwd_high_atr"] >= delta_atr
        ran_away = (~filled) & (hist["fwd_low_atr"] <= -tp_atr)
    n = len(hist)
    return {"n": n, "fill_probability": round(float(filled.mean()), 3),
            "missed_move_probability": round(float(ran_away.mean()), 3),
            "label_ar": "تكرار تاريخي (غير معاير)"}
