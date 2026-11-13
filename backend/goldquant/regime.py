"""Market regime classification from as-of features."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Regime:
    trend: str  # TREND_UP | TREND_DOWN | RANGE | TRANSITION
    vol: str  # LOW | NORMAL | HIGH | EXTREME
    vol_percentile: float
    er: float
    vr: float
    bars_since_break: float

    @property
    def label(self) -> str:
        return f"{self.trend}|VOL_{self.vol}"

    @property
    def label_ar(self) -> str:
        t = {"TREND_UP": "اتجاه صاعد", "TREND_DOWN": "اتجاه هابط", "RANGE": "تذبذب عرضي",
             "TRANSITION": "انتقالي"}[self.trend]
        v = {"LOW": "تقلب منخفض", "NORMAL": "تقلب عادي", "HIGH": "تقلب مرتفع", "EXTREME": "تقلب حاد"}[self.vol]
        return f"{t} / {v}"


def classify(feats: pd.DataFrame, lookback: int = 500) -> Regime:
    row = feats.iloc[-1]
    hist = feats["rv16"].dropna().tail(lookback)
    pct = float((hist <= row["rv16"]).mean()) if len(hist) > 50 and not np.isnan(row["rv16"]) else float("nan")
    if np.isnan(pct):
        vol = "NORMAL"
    elif pct >= 0.97:
        vol = "EXTREME"
    elif pct >= 0.80:
        vol = "HIGH"
    elif pct <= 0.20:
        vol = "LOW"
    else:
        vol = "NORMAL"
    er, vr, slope = float(row["er20"]), float(row["vr4"]), float(row["slope_ema50_atr"])
    if er >= 0.30 and vr >= 1.0 and abs(slope) >= 0.15:
        trend = "TREND_UP" if slope > 0 else "TREND_DOWN"
    elif er < 0.18 or vr < 0.85:
        trend = "RANGE"
    else:
        trend = "TRANSITION"
    return Regime(trend=trend, vol=vol, vol_percentile=pct, er=er, vr=vr,
                  bars_since_break=float(row["since_break"]))


def volatility_regime(r: Regime, last_ret_z: float) -> str:
    """V2 #6 four-state view: STRONG_TREND | RANGE | HIGH_VOL | EXCEPTIONAL."""
    if r.vol == "EXTREME" or abs(last_ret_z) > 6:
        return "EXCEPTIONAL"
    if r.vol == "HIGH":
        return "HIGH_VOL"
    if r.trend in ("TREND_UP", "TREND_DOWN"):
        return "STRONG_TREND"
    return "RANGE"


VOL_REGIME_AR = {"STRONG_TREND": "اتجاه قوي", "RANGE": "تذبذب عرضي", "HIGH_VOL": "تقلب مرتفع",
                 "EXCEPTIONAL": "ظروف استثنائية"}
