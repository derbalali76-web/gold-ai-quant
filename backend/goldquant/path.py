"""Probabilistic Path Engine (V2 #9).

For a trade with fixed levels (SL = 2×ATR(M15), TP1 = 1R) estimates, for each horizon in
15/30/60/240 minutes, the probabilities of three mutually exclusive outcomes:
    TP first  |  SL first  |  neither within the horizon
using a multinomial logistic model on as-of features. Validation is purged walk-forward against the
climatology baseline (class frequencies known at training time). A horizon is "qualified" for display
only if it beats climatology on the multiclass Brier score AND its reliability curve for P(TP) is within
tolerance AND it has enough out-of-sample samples. Nothing here is shown in DEMO mode.

v0.2 — PRE-REGISTERED 2026-11-16, committed before any v0.2 result was seen. One attempt, nothing tuned.
  Diagnosis of v0.1 (trained 2026-11-16): the bulk of P(TP) is well calibrated, but the gate fails on thin extreme
  bins (n = 90..629, gap up to 0.15 at 30 min) and on a systematic under-prediction in the lowest 240-min bin
  (0.081 predicted vs 0.137 observed, n = 7037).
  Change (the model itself is unchanged): post-hoc calibration. Inside every training window the LAST 20% of
  decision times is a calibration window; the logistic model is fitted only on rows whose outcome was known before
  that window minus the embargo; one-vs-rest isotonic (Platt below 1000 rows) is fitted on the calibration window
  and the three probabilities are renormalised (precision.calibration.calibrate_three_class).
  Gate UNCHANGED: >= MIN_OOS out-of-sample rows, multiclass Brier better than climatology by MIN_BRIER_IMPROVEMENT,
  max |mean predicted - observed| of P(TP) <= MAX_RELIABILITY_GAP over 10 equal-width bins with >= MIN_CAL_BIN rows.
  Stricter than v0.1: the final 20% holdout (never used before) must pass the SAME gate too; a horizon is qualified
  only if walk-forward AND holdout pass. If v0.2 fails, the probabilities stay unavailable; the gate is not relaxed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import model as M

PATH_VERSION = "path-mlogit-0.2.0"
CAL_FRAC = 0.2  # last share of each training window used only to fit the calibrator
HORIZONS_MIN = (15, 30, 60, 240)
CLASSES = (1, -1, 0)  # TP, SL, NEITHER
MIN_OOS = 1000
MIN_CAL_BIN = 50
MAX_RELIABILITY_GAP = 0.05
MIN_BRIER_IMPROVEMENT = 0.002


def build_path_dataset(m15: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame) -> pd.DataFrame:
    table = M.build_feature_table(m15, h1, h4)
    parts = []
    for d in (1, -1):
        part = table.copy()
        for c in M.DIRECTIONAL:
            part[c] = part[c] * d
        part["dir"] = float(d)
        for h in HORIZONS_MIN:
            out, res = M.barrier_outcomes(m15, table["atr"].to_numpy(), d, horizon=h // 15)
            part[f"out_{h}"] = out
            part[f"known_{h}"] = pd.to_datetime(res, unit="m", utc=True)
        parts.append(part)
    ds = pd.concat(parts).dropna(subset=M.FEATURES)
    ds["decision_time"] = ds.index
    return ds.sort_values(["decision_time", "dir"])


def _onehot(y: np.ndarray) -> np.ndarray:
    return np.stack([(y == c).astype(float) for c in CLASSES], axis=1)


def _fit(x: np.ndarray, y: np.ndarray):
    m = make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=1000))
    m.fit(x, y)
    return m


def _fit_cal(tr: pd.DataFrame, h: int):
    """v0.2: model on the earlier part of the window, calibrator on its last CAL_FRAC (purged in between).
    Returns (model, (cal_p, cal_y)) or None when either part is too small."""
    t = tr["decision_time"].sort_values().unique()
    if len(t) < 50:
        return None
    c0 = t[int(len(t) * (1 - CAL_FRAC))]
    fit = tr[tr[f"known_{h}"] < c0 - pd.Timedelta(minutes=h)]
    cal = tr[tr["decision_time"] >= c0]
    if len(fit) < 1000 or len(cal) < 300 or fit[f"out_{h}"].nunique() < 2:
        return None
    m = _fit(fit[M.FEATURES].to_numpy(), fit[f"out_{h}"].to_numpy())
    return m, (_proba(m, cal[M.FEATURES].to_numpy()), cal[f"out_{h}"].to_numpy())


def _apply_cal(cal, p: np.ndarray) -> np.ndarray:
    from .precision.calibration import calibrate_three_class
    return calibrate_three_class(cal[0], cal[1], p) if cal is not None else p


def _gate(rep, p: np.ndarray, y: np.ndarray, c: np.ndarray, prefix: str = "") -> tuple:
    """The unchanged v0.1 gate on one set of out-of-sample predictions. Returns (passed, reason, stats)."""
    oh = _onehot(y)
    n = len(y)
    bm = float(np.mean(np.sum((p - oh) ** 2, axis=1)))
    bc = float(np.mean(np.sum((c - oh) ** 2, axis=1)))
    bins = np.linspace(0, 1, 11)
    idx = np.clip(np.digitize(p[:, 0], bins) - 1, 0, 9)
    rel, gaps = [], []
    for b in range(10):
        mask = idx == b
        if mask.sum() >= MIN_CAL_BIN:
            mp, ob = float(p[mask, 0].mean()), float(oh[mask, 0].mean())
            rel.append({"bin": f"{bins[b]:.1f}-{bins[b+1]:.1f}", "n": int(mask.sum()), "mean_pred": round(mp, 4),
                        "observed": round(ob, 4)})
            gaps.append(abs(mp - ob))
    gap = float(max(gaps)) if gaps else float("nan")
    if n < MIN_OOS:
        why = "عينات خارج العينة أقل من الحد الأدنى"
    elif not bm < bc - MIN_BRIER_IMPROVEMENT:
        why = "لا يتفوق على التكرار التاريخي البسيط (climatology)"
    elif not gap <= MAX_RELIABILITY_GAP:
        why = "المعايرة غير كافية (فجوة منحنى الموثوقية كبيرة)"
    else:
        why = ""
    return (why == ""), prefix + why, {"n": n, "brier_model": bm, "brier_climatology": bc, "reliability": rel, "gap": gap}


def _proba(m, x: np.ndarray) -> np.ndarray:
    """Return probabilities ordered as CLASSES; classes unseen in training get 0."""
    p = m.predict_proba(x)
    cls = list(m.classes_)
    return np.stack([p[:, cls.index(c)] if c in cls else np.zeros(len(x)) for c in CLASSES], axis=1)


@dataclass
class HorizonReport:
    horizon_minutes: int
    n_oos: int = 0
    brier_model: float = float("nan")
    brier_climatology: float = float("nan")
    reliability_tp: list = field(default_factory=list)
    max_reliability_gap: float = float("nan")
    qualified: bool = False
    reason: str = ""
    holdout: dict = field(default_factory=dict)  # v0.2: the same gate on the final 20% (never used before)


def walk_forward_horizon(ds: pd.DataFrame, h: int, n_folds: int = 5, holdout_frac: float = 0.2,
                         calibrate: bool = True) -> HorizonReport:
    rep = HorizonReport(h)
    d = ds.dropna(subset=[f"out_{h}"])
    times = d["decision_time"].sort_values().unique()
    if len(times) < 500:
        rep.reason = "عينات غير كافية"
        return rep
    cut = times[int(len(times) * (1 - holdout_frac))]
    dev = d[d["decision_time"] < cut]
    dt = dev["decision_time"].sort_values().unique()
    edges = np.linspace(len(dt) * 0.4, len(dt), n_folds + 1).astype(int)
    P, Y, C = [], [], []
    embargo = pd.Timedelta(minutes=h)
    for a, b in zip(edges[:-1], edges[1:]):
        t0, t1 = dt[a], dt[min(b, len(dt) - 1)]
        tr = dev[dev[f"known_{h}"] < t0 - embargo]  # purge
        te = dev[(dev["decision_time"] >= t0) & (dev["decision_time"] < t1)]
        if len(tr) < 1000 or te.empty or tr[f"out_{h}"].nunique() < 2:
            continue
        if calibrate:
            fc = _fit_cal(tr, h)
            if fc is None:
                continue
            m, cal = fc
            P.append(_apply_cal(cal, _proba(m, te[M.FEATURES].to_numpy())))
        else:
            m = _fit(tr[M.FEATURES].to_numpy(), tr[f"out_{h}"].to_numpy())
            P.append(_proba(m, te[M.FEATURES].to_numpy()))
        y = te[f"out_{h}"].to_numpy()
        Y.append(y)
        clim = _onehot(tr[f"out_{h}"].to_numpy()).mean(axis=0)
        C.append(np.tile(clim, (len(y), 1)))
    if not P:
        rep.reason = "لم يكتمل أي طيّ للتحقق"
        return rep
    p, y, c = np.concatenate(P), np.concatenate(Y), np.concatenate(C)
    oh = _onehot(y)
    rep.n_oos = len(y)
    rep.brier_model = float(np.mean(np.sum((p - oh) ** 2, axis=1)))
    rep.brier_climatology = float(np.mean(np.sum((c - oh) ** 2, axis=1)))
    bins = np.linspace(0, 1, 11)
    idx = np.clip(np.digitize(p[:, 0], bins) - 1, 0, 9)
    gaps = []
    for b in range(10):
        mask = idx == b
        if mask.sum() >= MIN_CAL_BIN:
            mp, ob = float(p[mask, 0].mean()), float(oh[mask, 0].mean())
            rep.reliability_tp.append({"bin": f"{bins[b]:.1f}-{bins[b+1]:.1f}", "n": int(mask.sum()),
                                       "mean_pred": round(mp, 4), "observed": round(ob, 4)})
            gaps.append(abs(mp - ob))
    rep.max_reliability_gap = float(max(gaps)) if gaps else float("nan")
    if rep.n_oos < MIN_OOS:
        rep.reason = "عينات خارج العينة أقل من الحد الأدنى"
    elif not rep.brier_model < rep.brier_climatology - MIN_BRIER_IMPROVEMENT:
        rep.reason = "لا يتفوق على التكرار التاريخي البسيط (climatology)"
    elif not (rep.max_reliability_gap <= MAX_RELIABILITY_GAP):
        rep.reason = "المعايرة غير كافية (فجوة منحنى الموثوقية كبيرة)"
    else:
        rep.qualified, rep.reason = True, "مؤهل"
    if not calibrate:
        return rep
    # v0.2: the final holdout, trained (and calibrated) only on rows known before it
    tr = d[d[f"known_{h}"] < cut - embargo]
    ho = d[d["decision_time"] >= cut]
    fc = _fit_cal(tr, h) if not ho.empty else None
    if fc is None:
        rep.holdout = {"passed": False, "reason": "لم يكتمل اختبار العيّنة المحجوزة"}
        rep.qualified, rep.reason = False, rep.holdout["reason"] if rep.qualified else rep.reason
        return rep
    m, cal = fc
    ph = _apply_cal(cal, _proba(m, ho[M.FEATURES].to_numpy()))
    yh = ho[f"out_{h}"].to_numpy()
    ch = np.tile(_onehot(tr[f"out_{h}"].to_numpy()).mean(axis=0), (len(yh), 1))
    ok, why, st = _gate(rep, ph, yh, ch, "العيّنة المحجوزة: ")
    rep.holdout = {"passed": ok, "reason": why if not ok else "مؤهل", "n": st["n"],
                   "brier_model": round(st["brier_model"], 5), "brier_climatology": round(st["brier_climatology"], 5),
                   "max_reliability_gap": round(st["gap"], 4), "reliability_tp": st["reliability"]}
    if rep.qualified and not ok:
        rep.qualified, rep.reason = False, why
    return rep


@dataclass
class PathModels:
    models: dict  # horizon -> fitted model (trained on everything known at as_of)
    reports: dict  # horizon -> HorizonReport
    climatology: dict  # horizon -> np.array over CLASSES
    trained_until: datetime
    version: str = PATH_VERSION
    calibration: dict = field(default_factory=dict)  # v0.2: horizon -> (cal_p, cal_y) from the last 20% window

    def predict(self, row: pd.DataFrame) -> dict:
        x = row[M.FEATURES].to_numpy()
        cal = getattr(self, "calibration", None) or {}
        return {h: _apply_cal(cal.get(h), _proba(m, x))[0] for h, m in self.models.items()}


def train_path_models(ds: pd.DataFrame, as_of: datetime, validate: bool = True) -> PathModels | None:
    ts = pd.Timestamp(as_of)
    models, reports, clim, cals = {}, {}, {}, {}
    for h in HORIZONS_MIN:
        known = ds[ds[f"known_{h}"] <= ts].dropna(subset=[f"out_{h}"])
        if len(known) < 2000 or known[f"out_{h}"].nunique() < 2:
            continue
        fc = _fit_cal(known, h)
        if fc is not None:
            models[h], cals[h] = fc
        else:
            models[h] = _fit(known[M.FEATURES].to_numpy(), known[f"out_{h}"].to_numpy())
        clim[h] = _onehot(known[f"out_{h}"].to_numpy()).mean(axis=0)
        reports[h] = walk_forward_horizon(known, h) if validate else HorizonReport(h, reason="not validated")
    if not models:
        return None
    return PathModels(models, reports, clim, as_of, calibration=cals)


def expected_net_return(p_tp: float, p_sl: float, risk: float, reward: float, cost: float) -> float:
    """USD/oz. The 'neither' outcome is valued at 0 gross (exit at market) minus cost — conservative."""
    return p_tp * reward - p_sl * risk - cost
