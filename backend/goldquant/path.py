"""Probabilistic Path Engine (V2 #9).

For a trade with fixed levels (SL = 2×ATR(M15), TP1 = 1R) estimates, for each horizon in
15/30/60/240 minutes, the probabilities of three mutually exclusive outcomes:
    TP first  |  SL first  |  neither within the horizon
using a multinomial logistic model on as-of features. Validation is purged walk-forward against the
climatology baseline (class frequencies known at training time). A horizon is "qualified" for display
only if it beats climatology on the multiclass Brier score AND its reliability curve for P(TP) is within
tolerance AND it has enough out-of-sample samples. Nothing here is shown in DEMO mode.
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

PATH_VERSION = "path-mlogit-0.1.0"
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


def walk_forward_horizon(ds: pd.DataFrame, h: int, n_folds: int = 5, holdout_frac: float = 0.2) -> HorizonReport:
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
    return rep


@dataclass
class PathModels:
    models: dict  # horizon -> fitted model (trained on everything known at as_of)
    reports: dict  # horizon -> HorizonReport
    climatology: dict  # horizon -> np.array over CLASSES
    trained_until: datetime
    version: str = PATH_VERSION

    def predict(self, row: pd.DataFrame) -> dict:
        x = row[M.FEATURES].to_numpy()
        return {h: _proba(m, x)[0] for h, m in self.models.items()}


def train_path_models(ds: pd.DataFrame, as_of: datetime, validate: bool = True) -> PathModels | None:
    ts = pd.Timestamp(as_of)
    models, reports, clim = {}, {}, {}
    for h in HORIZONS_MIN:
        known = ds[ds[f"known_{h}"] <= ts].dropna(subset=[f"out_{h}"])
        if len(known) < 2000 or known[f"out_{h}"].nunique() < 2:
            continue
        models[h] = _fit(known[M.FEATURES].to_numpy(), known[f"out_{h}"].to_numpy())
        clim[h] = _onehot(known[f"out_{h}"].to_numpy()).mean(axis=0)
        reports[h] = walk_forward_horizon(known, h) if validate else HorizonReport(h, reason="not validated")
    if not models:
        return None
    return PathModels(models, reports, clim, as_of)


def expected_net_return(p_tp: float, p_sl: float, risk: float, reward: float, cost: float) -> float:
    """USD/oz. The 'neither' outcome is valued at 0 gross (exit at market) minus cost — conservative."""
    return p_tp * reward - p_sl * risk - cost
