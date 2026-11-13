"""Nested, purged walk-forward evaluation of the V3 precision layer.

For each test block (all inside the DEVELOPMENT period; the final holdout is never touched here):

    |------- train -------| emb |---- calibration ----| emb |---- test ----|
    primary/meta/experts      calibrators, thresholds,      evaluation only
    fitted here               consensus cut chosen here

* Primary model  = multinomial logit (the production path model) trained on both directions.
* Meta-labeling  = gradient boosting trained on OUT-OF-SAMPLE primary predictions inside the train window
                   (inner forward chaining), target = trade is profitable AFTER costs.
* Calibration    = fitted on the calibration window only.
* Selective      = acceptance threshold chosen on the calibration window only (maximise mean net pnl).
* Consensus      = disagreement between independent models (logit, gradient boosting, kNN).
* Mixture of experts = one logit per volatility regime, gated by the as-of regime.
Embargo = horizon, and training rows must have their outcome KNOWN before the next window starts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .. import model as M
from ..model import wilson
from ..risk import EST_SLIPPAGE, EST_SPREAD
from . import calibration as CAL
from .data import VREG

CLASSES = (1, -1, 0)
COST = EST_SPREAD + EST_SLIPPAGE
MIN_EDGE_R = 0.03  # minimum expected net edge, in R, for the EV-based rules
META_EXTRA = ["bias_abs", "er20", "vr4", "vol_ratio", "range_z", "log_since_break", "h4_er20"]


def _logit():
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=1000))


def _proba(m, X):
    p = m.predict_proba(X)
    cls = list(m.classes_)
    return np.stack([p[:, cls.index(c)] if c in cls else np.zeros(len(X)) for c in CLASSES], axis=1)


def ev_r(p: np.ndarray, tp_r: float, risk: np.ndarray) -> np.ndarray:
    """Expected net return in R units: p_tp*tp_r - p_sl*1 - cost/R ('neither' valued at 0 gross)."""
    return p[:, 0] * tp_r - p[:, 1] - COST / risk


def meta_features(S: pd.DataFrame, p: np.ndarray, tp_r: float) -> np.ndarray:
    risk = S["atr"].to_numpy() * S.attrs.get("stop_atr", 2.0)
    sess = np.stack([(S["session"] == s).to_numpy(float) for s in M.SESSIONS], axis=1)
    vr = np.stack([(S["vreg"] == v).to_numpy(float) for v in VREG], axis=1)
    return np.column_stack([p[:, 0], p[:, 1], ev_r(p, tp_r, risk), S[META_EXTRA].to_numpy(float), sess, vr])


def block_bootstrap_mean(x: np.ndarray, days: np.ndarray, n_boot: int = 1000, seed: int = 0) -> list | None:
    """95 % CI for the mean, resampling whole DAYS (overlapping trades are correlated within a day)."""
    if len(x) < 20:
        return None
    rng = np.random.default_rng(seed)
    groups = pd.Series(x).groupby(days).agg(["sum", "count"])
    s, c = groups["sum"].to_numpy(), groups["count"].to_numpy()
    k = len(s)
    if k < 5:
        return None
    idx = rng.integers(0, k, size=(n_boot, k))
    means = s[idx].sum(axis=1) / c[idx].sum(axis=1)
    return [round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)]


def summarize(pnl: np.ndarray, out: np.ndarray, days: np.ndarray, opportunities: int) -> dict:
    n = len(pnl)
    if n == 0:
        return {"accepted": 0, "coverage": 0.0, "win_rate": None, "win_rate_ci95": None, "tp_rate": None,
                "ev_per_trade": None, "ev_ci95": None, "total_pnl": 0.0}
    wins = int((pnl > 0).sum())
    lo, hi = wilson(wins, n)
    return {"accepted": n, "coverage": round(n / opportunities, 4), "win_rate": round(wins / n, 4),
            "win_rate_ci95": [round(float(lo), 4), round(float(hi), 4)], "tp_rate": round(float((out == 1).mean()), 4),
            "ev_per_trade": round(float(pnl.mean()), 4), "ev_ci95": block_bootstrap_mean(pnl, days),
            "total_pnl": round(float(pnl.sum()), 2)}


def _choose_threshold(score: np.ndarray, pnl: np.ndarray, min_accept: int) -> float | None:
    """Threshold on `score` maximising mean net pnl on the CALIBRATION window (never on test)."""
    best, best_t = -np.inf, None
    for q in np.linspace(0.0, 0.98, 50):
        t = float(np.quantile(score, q))
        m = score >= t
        if m.sum() < min_accept:
            break
        v = pnl[m].mean()
        if v > best:
            best, best_t = v, t
    return best_t


@dataclass
class FoldResult:
    fold: int
    train_end: str
    cal: tuple
    test: tuple
    n_train: int
    n_cal: int
    n_test: int
    tau_meta: float | None
    rules: dict = field(default_factory=dict)


def _fit_primary(ds: pd.DataFrame, before: pd.Timestamp, h: int = 240):
    tr = ds[ds[f"known_{h}"] < before].dropna(subset=[f"out_{h}"])
    if len(tr) < 2000 or tr[f"out_{h}"].nunique() < 3:
        return None, tr
    return _logit().fit(tr[M.FEATURES].to_numpy(), tr[f"out_{h}"].to_numpy()), tr


def fit_bundle(S: pd.DataFrame, ds: pd.DataFrame, tr_end, c0, c1, seed: int = 0) -> dict | None:
    """Fit everything for one window triple. S = signal rows (time-sorted), ds = path dataset with 'vreg'.
    Training uses outcomes known before tr_end; calibration/thresholds use decisions in [c0, c1)."""
    h = S.attrs.get("horizon_min", 240)
    tp_r = S.attrs.get("tp_r", 1.0)
    stop_atr = S.attrs.get("stop_atr", 2.0)
    emb = pd.Timedelta(minutes=h)
    cal = S[(S["decision_time"] >= c0) & (S["decision_time"] < c1)]
    prim, tr_rows = _fit_primary(ds, tr_end, h)
    if prim is None or len(cal) < 200:
        return None
    Xc = cal[M.FEATURES].to_numpy()
    pc = _proba(prim, Xc)
    # meta-labeling on OUT-OF-SAMPLE primary predictions (inner forward chaining inside the train window)
    trS = S[S["known_at"] < tr_end]
    mx, my = [], []
    for ch in np.array_split(np.arange(len(trS)), 4)[1:]:
        if len(ch) == 0:
            continue
        inner, _ = _fit_primary(ds, trS["decision_time"].iloc[ch[0]] - emb, h)
        if inner is None:
            continue
        part = trS.iloc[ch]
        mx.append(meta_features(part, _proba(inner, part[M.FEATURES].to_numpy()), tp_r))
        my.append((part["pnl"] > 0).to_numpy(int))
    meta = mcal = tau = None
    if mx and sum(len(y) for y in my) >= 500 and len(np.unique(np.concatenate(my))) == 2:
        meta = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, l2_regularization=1.0,
                                              min_samples_leaf=100, random_state=seed).fit(np.vstack(mx), np.concatenate(my))
        mc = meta.predict_proba(meta_features(cal, pc, tp_r))[:, 1]
        mcal = CAL.Calibrator().fit(mc, (cal["pnl"] > 0).to_numpy(float))
        tau = _choose_threshold(mcal.transform(mc), cal["pnl"].to_numpy(), max(30, int(0.05 * len(cal))))
    X_tr, y_tr = tr_rows[M.FEATURES].to_numpy(), tr_rows[f"out_{h}"].to_numpy()
    hgb = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=200,
                                         random_state=seed).fit(X_tr, y_tr)
    knn = make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=100)).fit(X_tr, y_tr)
    experts = {}
    for v in VREG:
        sub = tr_rows[tr_rows["vreg"] == v]
        if len(sub) >= 1000 and sub[f"out_{h}"].nunique() == 3:
            experts[v] = _logit().fit(sub[M.FEATURES].to_numpy(), sub[f"out_{h}"].to_numpy())
    risk_c = cal["atr"].to_numpy() * stop_atr
    dis_c = np.std(np.stack([ev_r(pc, tp_r, risk_c), ev_r(_proba(hgb, Xc), tp_r, risk_c),
                             ev_r(_proba(knn, Xc), tp_r, risk_c)]), axis=0)
    return {"primary": prim, "cal_p": pc, "cal_y": cal["out"].to_numpy(), "meta": meta, "meta_cal": mcal, "tau": tau,
            "hgb": hgb, "knn": knn, "experts": experts, "dis_cut": float(np.median(dis_c)), "tp_r": tp_r,
            "stop_atr": stop_atr, "n_train": len(tr_rows), "n_cal": len(cal)}


def apply_bundle(b: dict, rows: pd.DataFrame) -> pd.DataFrame:
    tp_r, X = b["tp_r"], rows[M.FEATURES].to_numpy()
    pt = _proba(b["primary"], X)
    pt_cal = CAL.calibrate_three_class(b["cal_p"], b["cal_y"], pt)
    p_hgb, p_knn = _proba(b["hgb"], X), _proba(b["knn"], X)
    p_moe = pt.copy()
    for v, m in b["experts"].items():
        mask = (rows["vreg"] == v).to_numpy()
        if mask.any():
            p_moe[mask] = _proba(m, X[mask])
    risk = rows["atr"].to_numpy() * b["stop_atr"]
    rec = rows[[c for c in ("decision_time", "pnl", "out", "dir", "vreg", "atr") if c in rows]].copy()
    rec["p_tp_raw"], rec["p_sl_raw"] = pt[:, 0], pt[:, 1]
    rec["p_tp_cal"], rec["p_sl_cal"] = pt_cal[:, 0], pt_cal[:, 1]
    rec["p_tp_hgb"], rec["p_tp_knn"], rec["p_tp_moe"], rec["p_sl_moe"] = p_hgb[:, 0], p_knn[:, 0], p_moe[:, 0], p_moe[:, 1]
    rec["ev_raw"], rec["ev_cal"], rec["ev_moe"] = ev_r(pt, tp_r, risk), ev_r(pt_cal, tp_r, risk), ev_r(p_moe, tp_r, risk)
    rec["ev_hgb"], rec["ev_knn"] = ev_r(p_hgb, tp_r, risk), ev_r(p_knn, tp_r, risk)
    rec["disagreement"] = np.std(rec[["ev_raw", "ev_hgb", "ev_knn"]].to_numpy(), axis=1)
    if b["meta"] is not None:
        rec["meta_p"] = b["meta_cal"].transform(b["meta"].predict_proba(meta_features(rows, pt, tp_r))[:, 1])
    else:
        rec["meta_p"] = np.nan
    rec["acc_baseline"] = True
    rec["acc_primary_ev"] = rec["ev_raw"] >= MIN_EDGE_R
    rec["acc_calibrated_ev"] = rec["ev_cal"] >= MIN_EDGE_R
    rec["acc_moe_ev"] = rec["ev_moe"] >= MIN_EDGE_R
    rec["acc_meta"] = (rec["meta_p"] >= b["tau"]) if b["tau"] is not None else False
    rec["acc_meta_consensus"] = rec["acc_meta"] & (rec["disagreement"] <= b["dis_cut"])
    return rec


def with_vreg(S: pd.DataFrame, ds: pd.DataFrame) -> pd.DataFrame:
    ds = ds.copy()
    ds["vreg"] = S.drop_duplicates("decision_time").set_index("decision_time")["vreg"].reindex(ds["decision_time"]).to_numpy()
    return ds


def run(S: pd.DataFrame, ds: pd.DataFrame, n_folds: int = 5, dev_frac: float = 0.8, cal_frac: float = 0.12,
        test_span_frac: float = 0.45, seed: int = 0, keep_models: bool = False) -> dict:
    h = S.attrs.get("horizon_min", 240)
    emb = pd.Timedelta(minutes=h)
    S = S.sort_values("decision_time")
    t_min, t_max = S["decision_time"].iloc[0], S["decision_time"].iloc[-1]
    span = t_max - t_min
    holdout_cut = t_min + dev_frac * span
    dev = S[S["decision_time"] < holdout_cut - emb]
    test_start0 = holdout_cut - test_span_frac * span
    edges = [test_start0 + (holdout_cut - test_start0) * k / n_folds for k in range(n_folds + 1)]
    cal_len = cal_frac * span
    ds = with_vreg(S, ds)
    rows, folds, models = [], [], []
    for f, (t0, t1) in enumerate(zip(edges[:-1], edges[1:])):
        c0, c1 = t0 - emb - cal_len, t0 - emb
        tr_end = c0 - emb
        test = dev[(dev["decision_time"] >= t0) & (dev["decision_time"] < t1)]
        if test.empty:
            continue
        b = fit_bundle(dev, ds, tr_end, c0, c1, seed)
        if b is None:
            continue
        rec = apply_bundle(b, test)
        rec["fold"] = f
        rows.append(rec)
        folds.append(FoldResult(f, str(tr_end), (str(c0), str(c1)), (str(t0), str(t1)), b["n_train"], b["n_cal"],
                                len(test), None if b["tau"] is None else round(float(b["tau"]), 4)))
        if keep_models:
            models.append({"fold": f, "primary": b["primary"], "meta": b["meta"], "meta_cal": b["meta_cal"],
                           "tau": b["tau"], "test": test})
    if not rows:
        return {"status": "INSUFFICIENT", "reason_ar": "بيانات غير كافية لتقييم متدرج متداخل"}
    return {"status": "OK", "oos": pd.concat(rows), "folds": folds, "models": models, "holdout_start": str(holdout_cut)}


RULES = {
    "acc_baseline": "قاعدة الاتجاه وحدها (كل الإشارات)",
    "acc_primary_ev": "النموذج الأساسي: عائد متوقع موجب (غير معاير) — القاعدة الإنتاجية الحالية",
    "acc_calibrated_ev": "عائد متوقع موجب باحتمالات مُعايرة",
    "acc_moe_ev": "Mixture of Experts: عائد متوقع موجب",
    "acc_meta": "Meta-Labeling + Selective Prediction",
    "acc_meta_consensus": "Meta-Labeling + Selective + Model Consensus",
}


def rule_report(oos: pd.DataFrame) -> dict:
    days = oos["decision_time"].dt.floor("D").to_numpy()
    opp = len(oos)
    out = {}
    for col, name in RULES.items():
        m = oos[col].to_numpy(bool)
        r = summarize(oos["pnl"].to_numpy()[m], oos["out"].to_numpy()[m], days[m], opp)
        per_fold = oos[m].groupby("fold")["pnl"].agg(["mean", "count"])
        r["per_fold_ev"] = {int(k): (round(float(v["mean"]), 4), int(v["count"])) for k, v in per_fold.iterrows()}
        r["name_ar"] = name
        out[col] = r
    return out


def frontier(oos: pd.DataFrame, score_col: str = "meta_p") -> list[dict]:
    """Precision–Coverage frontier on pooled OOS predictions. DESCRIPTIVE: the quantile grid is fixed in
    advance and no point of it is used to pick the production threshold (that comes from calibration windows)."""
    d = oos.dropna(subset=[score_col])
    days = d["decision_time"].dt.floor("D").to_numpy()
    s = d[score_col].to_numpy()
    out = []
    for q in (0.0, 0.5, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99):
        t = float(np.quantile(s, q))
        m = s >= t
        r = summarize(d["pnl"].to_numpy()[m], d["out"].to_numpy()[m], days[m], len(d))
        r["threshold_quantile"], r["threshold"] = q, round(t, 4)
        r["precision_95_proven"] = bool(r["win_rate_ci95"] and r["win_rate_ci95"][0] >= 0.95)
        out.append(r)
    return out


def calibration_report(oos: pd.DataFrame) -> dict:
    y_tp = (oos["out"] == 1).to_numpy(float)
    y_win = (oos["pnl"] > 0).to_numpy(float)
    rep = {}
    for name, p, y in (("primary_raw_p_tp", oos["p_tp_raw"].to_numpy(), y_tp),
                       ("primary_calibrated_p_tp", oos["p_tp_cal"].to_numpy(), y_tp),
                       ("meta_calibrated_p_profit", oos["meta_p"].to_numpy(), y_win)):
        ok = ~np.isnan(p)
        if ok.sum() == 0:
            continue
        v = CAL.verdict(p[ok], y[ok])
        rep[name] = {"verdict": v.__dict__, "decomposition": CAL.brier_decomposition(p[ok], y[ok]),
                     "reliability": CAL.reliability_table(p[ok], y[ok])}
    return rep


def consensus_report(oos: pd.DataFrame) -> dict:
    y = (oos["out"] == 1).to_numpy(float)
    briers = {k: round(float(np.mean((oos[c] - y) ** 2)), 5)
              for k, c in (("logit", "p_tp_raw"), ("gradient_boosting", "p_tp_hgb"), ("knn", "p_tp_knn"), ("moe", "p_tp_moe"))}
    signs = np.sign(oos[["ev_raw", "ev_hgb", "ev_knn"]].to_numpy())
    agree = float(np.mean(np.all(signs == signs[:, :1], axis=1)))
    lo = oos["disagreement"] <= oos["disagreement"].median()
    return {"brier_p_tp_by_model": briers, "all_models_agree_on_ev_sign": round(agree, 4),
            "ev_when_models_agree": round(float(oos.loc[lo, "pnl"].mean()), 4),
            "ev_when_models_disagree": round(float(oos.loc[~lo, "pnl"].mean()), 4)}
