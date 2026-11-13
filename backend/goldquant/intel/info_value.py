"""Information Value Engine (V2 #19): marginal predictive value of each feature group + redundancy map.

Leave-one-group-out on the purged walk-forward multiclass Brier. A group whose removal does not worsen the
score adds no information. Highly correlated features (|rho| > 0.8) are clustered so they are not counted
as independent evidence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import model as M
from .. import path as P

GROUPS = {
    "trend_m15": ["dist_ema20_atr", "slope_ema50_atr", "ret_4", "ret_16"],
    "trend_htf": ["h1_slope_ema50_atr", "h1_dist_ema20_atr", "h4_slope_ema50_atr", "h4_dist_ema20_atr"],
    "efficiency": ["er20", "vr4", "h1_er20", "h4_er20"],
    "volatility": ["vol_ratio", "range_z", "ret_z"],
    "structure_break": ["log_since_break"],
    "session": [f"sess_{s}" for s in P.M.SESSIONS],
}


def redundancy(ds: pd.DataFrame, threshold: float = 0.8) -> list[list[str]]:
    feats = [f for f in M.FEATURES if f != "dir" and ds[f].std() > 0]
    c = ds[feats].corr(method="spearman").abs().to_numpy()
    seen, clusters = set(), []
    for i, f in enumerate(feats):
        if f in seen:
            continue
        grp = [feats[j] for j in range(len(feats)) if c[i, j] >= threshold]
        if len(grp) > 1:
            clusters.append(grp)
            seen.update(grp)
    return clusters


def ablation(ds: pd.DataFrame, horizon: int = 240) -> dict:
    full = P.walk_forward_horizon(ds, horizon)
    out = {"full_brier": full.brier_model, "climatology_brier": full.brier_climatology, "groups": {}}
    original = list(M.FEATURES)
    try:
        for g, cols in GROUPS.items():
            M.FEATURES[:] = [f for f in original if f not in cols]
            r = P.walk_forward_horizon(ds, horizon)
            out["groups"][g] = {"brier_without": r.brier_model,
                                "marginal_value": round(r.brier_model - full.brier_model, 5)}
    finally:
        M.FEATURES[:] = original
    out["redundant_clusters"] = redundancy(ds)
    out["note_ar"] = "قيمة موجبة = حذف المجموعة يُسيء التنبؤ (إذن تحمل معلومة). قيمة ≤ 0 = لا تضيف شيئاً."
    return out
