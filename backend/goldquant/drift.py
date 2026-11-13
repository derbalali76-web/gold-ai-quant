"""Model Drift Sentinel (V2 #11): feature drift (PSI) and performance drift on resolved predictions."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from .msg import M

PSI_ALARM = 0.25
PSI_FEATURES_FOR_ALARM = 3
BRIER_DEGRADATION_ALARM = 0.03


def psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index with quantile bins from the reference sample."""
    reference = reference[~np.isnan(reference)]
    current = current[~np.isnan(current)]
    if len(reference) < 100 or len(current) < 30:
        return float("nan")
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    r = np.histogram(reference, edges)[0] / len(reference)
    c = np.histogram(current, edges)[0] / len(current)
    r, c = np.clip(r, 1e-4, None), np.clip(c, 1e-4, None)
    return float(np.sum((c - r) * np.log(c / r)))


@dataclass
class DriftReport:
    feature_psi: dict = field(default_factory=dict)
    drifted_features: list = field(default_factory=list)
    brier_reference: float | None = None
    brier_recent: float | None = None
    alarm: bool = False
    reasons_ar: list = field(default_factory=list)


def check(reference: pd.DataFrame, recent: pd.DataFrame, features: list[str],
          ref_brier: float | None = None, recent_brier: float | None = None) -> DriftReport:
    rep = DriftReport(brier_reference=ref_brier, brier_recent=recent_brier)
    for f in features:
        v = psi(reference[f].to_numpy(dtype=float), recent[f].to_numpy(dtype=float))
        rep.feature_psi[f] = None if np.isnan(v) else round(v, 4)
        if not np.isnan(v) and v > PSI_ALARM:
            rep.drifted_features.append(f)
    if len(rep.drifted_features) >= PSI_FEATURES_FOR_ALARM:
        rep.alarm = True
        rep.reasons_ar.append(M("dr.psi", len(rep.drifted_features), PSI_ALARM))
    if ref_brier is not None and recent_brier is not None and recent_brier > ref_brier + BRIER_DEGRADATION_ALARM:
        rep.alarm = True
        rep.reasons_ar.append(M("dr.perf"))
    return rep
