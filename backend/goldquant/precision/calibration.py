"""Probability Calibration (V3 #4).

Calibrators are ALWAYS fitted on predictions for a calibration window that lies strictly after the model's
training window and strictly before the evaluation window (with an embargo), so neither model training nor
calibration ever sees evaluation outcomes.

Calibration tests (all must pass before any number is shown to the user):
  * n >= MIN_N evaluation samples
  * Expected Calibration Error (equal-mass bins) <= MAX_ECE
  * Spiegelhalter Z-test p-value >= 0.05 (no significant miscalibration)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

MIN_N = 300
MAX_ECE = 0.03


class Calibrator:
    """method: 'isotonic' | 'platt' | 'none'. Platt is used automatically when the window is small."""

    def __init__(self, method: str = "auto"):
        self.method = method
        self._m = None

    def fit(self, p: np.ndarray, y: np.ndarray) -> "Calibrator":
        p, y = np.asarray(p, float), np.asarray(y, float)
        m = self.method
        if m == "auto":
            m = "isotonic" if len(p) >= 1000 else "platt"
        self.method_used = m
        if len(np.unique(y)) < 2 or m == "none":
            self.method_used = "none"
            return self
        if m == "isotonic":
            self._m = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(p, y)
        else:
            lg = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
            self._m = LogisticRegression(C=1e6, max_iter=1000).fit(lg.reshape(-1, 1), y)
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        p = np.asarray(p, float)
        if self._m is None:
            return p
        if self.method_used == "isotonic":
            return np.clip(self._m.predict(p), 1e-4, 1 - 1e-4)
        lg = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
        return self._m.predict_proba(lg.reshape(-1, 1))[:, 1]


def calibrate_three_class(cal_p: np.ndarray, cal_y: np.ndarray, test_p: np.ndarray) -> np.ndarray:
    """One-vs-rest calibration for (TP, SL, NEITHER) then renormalisation to a valid simplex."""
    classes = (1, -1, 0)
    out = np.zeros_like(test_p, dtype=float)
    for k, c in enumerate(classes):
        out[:, k] = Calibrator().fit(cal_p[:, k], (cal_y == c).astype(float)).transform(test_p[:, k])
    s = out.sum(axis=1, keepdims=True)
    s[s == 0] = 1.0
    return out / s


def ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    if len(p) == 0:
        return float("nan")
    order = np.argsort(p)
    chunks = np.array_split(order, bins)
    return float(sum(len(c) / len(p) * abs(p[c].mean() - y[c].mean()) for c in chunks if len(c)))


def spiegelhalter(p: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    p, y = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6), np.asarray(y, float)
    num = np.sum((y - p) * (1 - 2 * p))
    den = np.sqrt(np.sum((1 - 2 * p) ** 2 * p * (1 - p)))
    z = float(num / den) if den > 0 else 0.0
    return z, float(2 * stats.norm.sf(abs(z)))


def brier_decomposition(p: np.ndarray, y: np.ndarray, bins: int = 10) -> dict:
    p, y = np.asarray(p, float), np.asarray(y, float)
    ybar = y.mean()
    order = np.argsort(p)
    rel = res = 0.0
    for c in np.array_split(order, bins):
        if len(c):
            w = len(c) / len(p)
            rel += w * (p[c].mean() - y[c].mean()) ** 2
            res += w * (y[c].mean() - ybar) ** 2
    return {"brier": float(np.mean((p - y) ** 2)), "reliability": float(rel), "resolution": float(res),
            "uncertainty": float(ybar * (1 - ybar))}


def reliability_table(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    order = np.argsort(p)
    return [{"n": int(len(c)), "mean_pred": round(float(p[c].mean()), 4), "observed": round(float(y[c].mean()), 4)}
            for c in np.array_split(order, bins) if len(c)]


@dataclass
class CalibrationVerdict:
    n: int
    ece: float
    spiegelhalter_z: float
    spiegelhalter_p: float
    passed: bool
    reason_ar: str


def verdict(p: np.ndarray, y: np.ndarray) -> CalibrationVerdict:
    n = len(p)
    if n < MIN_N:
        return CalibrationVerdict(n, float("nan"), float("nan"), float("nan"), False, f"عينة المعايرة {n} أقل من {MIN_N}")
    e = ece(p, y)
    z, pv = spiegelhalter(p, y)
    if e > MAX_ECE:
        return CalibrationVerdict(n, e, z, pv, False, f"خطأ المعايرة ECE={e:.3f} أكبر من {MAX_ECE}")
    if pv < 0.05:
        return CalibrationVerdict(n, e, z, pv, False, f"اختبار Spiegelhalter يرفض المعايرة (p={pv:.3f})")
    return CalibrationVerdict(n, e, z, pv, True, "اجتاز اختبارات المعايرة")
