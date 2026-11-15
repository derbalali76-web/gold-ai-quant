"""Market-activity forecast for scalpers: will price move at least TARGET (either way) within the next 4 hours?

Direction is not predictable after costs (scalping lab rounds 1-3). Volatility is: it clusters. This model only
answers "is the market moving enough for a +0.65 % scalp right now?" — it never says buy or sell.

Pre-registered (2026-11-15, BEFORE any result was seen):
  label    1 if, within the next 16 x 15-min bars, the high reaches close*(1+0.65 %) OR the low reaches close*(1-0.65 %)
  features recent realised volatility (1 h, 4 h, 24 h, 7 d), last-4h range, volume vs 7 d, hour-of-day, weekend
  model    logistic regression, re-fit each fold on all earlier data (expanding window), 16-bar purge gap
  folds    calendar years 2022 ... now, the last 20 % of time is a final holdout never used to choose anything
  baseline the hit rate for the same hour-of-week, learned on the same training data (the "usual" activity)
  qualifies only if ALL hold:
    1. Brier skill score vs baseline, 99 % day-block bootstrap CI above zero (all out-of-sample predictions)
    2. skill positive in every fold and in the final holdout
    3. calibrated: in every probability bin with >= 300 predictions, |predicted - actual| <= 5 points

Attempt 1 (raw logistic) had real skill in every fold and the holdout but FAILED rule 3 (overconfident at the low
end). Attempt 2, declared before running it and the ONLY other attempt allowed: same model fitted on the training
data minus its last 12 months, then an isotonic recalibration learned on those last 12 months (still strictly before
the test period). Same three rules.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

TARGET = 0.0065
HORIZON = 16  # 4 h of 15-min bars
STEP = 4  # one prediction per hour (labels overlap less, faster)
HOLDOUT_FRAC = 0.2
CI_LEVEL = 99.0
BINS = (0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.01)
FEATURES = ("rv4", "rv16", "rv96", "rv672", "rng16", "volz", "hsin", "hcos", "wkend")


def labels(df: pd.DataFrame) -> np.ndarray:
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    n = len(c)
    fh = pd.Series(h[::-1]).rolling(HORIZON, min_periods=HORIZON).max().to_numpy()[::-1]
    fl = pd.Series(lo[::-1]).rolling(HORIZON, min_periods=HORIZON).min().to_numpy()[::-1]
    # window i+1 .. i+HORIZON
    up = np.full(n, np.nan)
    dn = np.full(n, np.nan)
    up[:-1] = fh[1:]
    dn[:-1] = fl[1:]
    y = ((up >= c * (1 + TARGET)) | (dn <= c * (1 - TARGET))).astype(float)
    y[np.isnan(up) | np.isnan(dn)] = np.nan
    return y


def features(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    r = np.log(c).diff()
    f = pd.DataFrame(index=df.index)
    for w in (4, 16, 96, 672):
        f[f"rv{w}"] = np.log(r.rolling(w, min_periods=w // 2).std() + 1e-6)
    f["rng16"] = np.log((df["high"].rolling(16).max() - df["low"].rolling(16).min()) / c + 1e-6)
    if "volume" in df.columns:
        v = np.log(df["volume"].replace(0, np.nan))
        f["volz"] = (v.rolling(4).mean() - v.rolling(672, min_periods=96).mean()).fillna(0.0)
    else:
        f["volz"] = 0.0
    close_t = df.index + pd.Timedelta(minutes=15)
    hr = close_t.hour + close_t.minute / 60
    f["hsin"] = np.sin(2 * np.pi * hr / 24)
    f["hcos"] = np.cos(2 * np.pi * hr / 24)
    f["wkend"] = (close_t.dayofweek >= 5).astype(float)
    return f


def _how(idx: pd.DatetimeIndex) -> np.ndarray:
    t = idx + pd.Timedelta(minutes=15)
    return (t.dayofweek * 24 + t.hour).to_numpy()


def _fit(X, y):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    m = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=500))
    m.fit(X, y)
    return m


class _Calibrated:
    def __init__(self, m, iso):
        self.m, self.iso = m, iso

    def predict_proba(self, X):
        p = self.iso.predict(self.m.predict_proba(X)[:, 1])
        return np.column_stack([1 - p, p])


def _fit_calibrated(X, y, t, gap):
    """Model on all but the last 12 months; isotonic map learned on the last 12 months (out of sample for the model)."""
    from sklearn.isotonic import IsotonicRegression
    split = t[-1] - pd.Timedelta(days=365)
    a = t < split - gap
    b = t >= split
    if a.sum() < 3000 or b.sum() < 1000:
        return _fit(X, y)
    m = _fit(X[a], y[a])
    iso = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip").fit(m.predict_proba(X[b])[:, 1], y[b])
    return _Calibrated(m, iso)


def _block_ci(day, a, b, level=CI_LEVEL, n=1000, seed=5):
    """Day-block bootstrap of Brier skill = 1 - sum(a)/sum(b) (a = model sq. errors, b = baseline sq. errors)."""
    u, inv = np.unique(day, return_inverse=True)
    sa = np.bincount(inv, a, len(u))
    sb = np.bincount(inv, b, len(u))
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        k = rng.integers(0, len(u), len(u))
        out.append(1 - sa[k].sum() / sb[k].sum())
    q = (100 - level) / 2
    return [round(float(np.percentile(out, q)), 4), round(float(np.percentile(out, 100 - q)), 4)]


def evaluate(df: pd.DataFrame, first_year: Optional[int] = None, calibrate: bool = True,
             return_preds: bool = False) -> dict:
    df = df.dropna(subset=["open", "high", "low", "close"])
    X = features(df)
    y = labels(df)
    ok = np.isfinite(X.to_numpy()).all(axis=1) & np.isfinite(y)
    keep = np.zeros(len(df), bool)
    keep[::STEP] = True
    keep &= ok
    idx = df.index[keep]
    Xk, yk, how = X.to_numpy()[keep], y[keep], _how(idx)
    out = {"calibrated": calibrate, "target_pct": TARGET * 100, "hours": HORIZON / 4, "period": f"{df.index[0].date()} -> {df.index[-1].date()}",
           "base_rate": round(float(yk.mean()), 4) if len(yk) else None, "folds": [], "qualified": False}
    if len(yk) < 5000:
        out["reason"] = "insufficient data"
        return out
    cut = idx[int(len(idx) * (1 - HOLDOUT_FRAC))]
    years = sorted(set(idx.year))
    first_year = first_year or years[1]
    bounds = [pd.Timestamp(f"{yr}-01-01", tz="UTC") for yr in years if yr >= first_year] + [cut]
    bounds = sorted(set(b for b in bounds if b <= cut)) + [idx[-1] + pd.Timedelta(minutes=1)]
    gap = pd.Timedelta(minutes=15 * HORIZON)
    P, B, Y, D, H, T = [], [], [], [], [], []
    for a, b in zip(bounds[:-1], bounds[1:]):
        tr = idx < a - gap
        te = (idx >= a) & (idx < b)
        if tr.sum() < 3000 or te.sum() < 200:
            continue
        m = _fit_calibrated(Xk[tr], yk[tr], idx[tr], gap) if calibrate else _fit(Xk[tr], yk[tr])
        p = m.predict_proba(Xk[te])[:, 1]
        clim = pd.Series(yk[tr]).groupby(how[tr]).mean()
        base = pd.Series(how[te]).map(clim).fillna(yk[tr].mean()).to_numpy()
        yt = yk[te]
        bs, bb = float(np.mean((p - yt) ** 2)), float(np.mean((base - yt) ** 2))
        out["folds"].append({"from": str(a.date()), "to": str(b.date()), "n": int(te.sum()),
                             "hit_rate": round(float(yt.mean()), 4), "skill": round(1 - bs / bb, 4),
                             "holdout": bool(a >= cut)})
        P.append(p); B.append(base); Y.append(yt); D.append(idx[te].floor("D").asi8); H.append(np.full(len(p), a >= cut))
        T.append(idx[te].tz_convert("UTC").tz_localize(None).to_numpy())
    if not P:
        out["reason"] = "no folds"
        return out
    p, base, yt, day, ho = (np.concatenate(v) for v in (P, B, Y, D, H))
    if return_preds:  # out-of-sample predictions, indexed by the 15-min bar they were made at (its open time)
        out["preds"] = pd.DataFrame({"p": p, "usual": base}, index=pd.DatetimeIndex(np.concatenate(T)).tz_localize("UTC"))
    ea, eb = (p - yt) ** 2, (base - yt) ** 2
    out["skill"] = round(float(1 - ea.sum() / eb.sum()), 4)
    out["skill_ci99"] = _block_ci(day, ea, eb)
    out["holdout_skill"] = round(float(1 - ea[ho].sum() / eb[ho].sum()), 4) if ho.any() else None
    cal = []
    for lo_, hi_ in zip(BINS[:-1], BINS[1:]):
        s = (p >= lo_) & (p < hi_)
        if s.sum():
            cal.append({"bin": f"{int(lo_ * 100)}-{min(int(hi_ * 100), 100)}%", "n": int(s.sum()),
                        "predicted": round(float(p[s].mean()), 4), "actual": round(float(yt[s].mean()), 4)})
    out["calibration"] = cal
    ck = {
        "skill CI above zero": out["skill_ci99"][0] > 0,
        "every fold positive": all(f["skill"] > 0 for f in out["folds"]),
        "holdout positive": bool(out["holdout_skill"] is not None and out["holdout_skill"] > 0),
        "calibrated (5 points)": all(abs(c["predicted"] - c["actual"]) <= 0.05 for c in cal if c["n"] >= 300),
    }
    out["checks"] = ck
    out["qualified"] = all(ck.values())
    out["reason"] = "qualified" if out["qualified"] else "failed: " + "; ".join(k for k, v in ck.items() if not v)
    return out


def fit_live(df: pd.DataFrame):
    """Fit on all labelled history; returns a callable giving P(move >= TARGET within 4 h) for the last closed bar."""
    df = df.dropna(subset=["open", "high", "low", "close"])
    X, y = features(df), labels(df)
    ok = np.isfinite(X.to_numpy()).all(axis=1) & np.isfinite(y)
    keep = np.zeros(len(df), bool)
    keep[::STEP] = True
    keep &= ok
    m = _fit_calibrated(X.to_numpy()[keep], y[keep], df.index[keep], pd.Timedelta(minutes=15 * HORIZON))
    clim = pd.Series(y[keep]).groupby(_how(df.index[keep])).mean()

    def predict(recent: pd.DataFrame) -> dict:
        f = features(recent).iloc[[-1]]
        if not np.isfinite(f.to_numpy()).all():
            return {"probability": None}
        p = float(m.predict_proba(f.to_numpy())[0, 1])
        usual = float(clim.get(int(_how(recent.index[-1:])[0]), y[keep].mean()))
        return {"probability": round(p, 3), "usual": round(usual, 3)}

    return predict


def export(df: pd.DataFrame, report: dict) -> dict:
    """Fit on all labelled history and return plain parameters (JSON) the API can apply without scikit-learn state."""
    df = df.dropna(subset=["open", "high", "low", "close"])
    X, y = features(df), labels(df)
    ok = np.isfinite(X.to_numpy()).all(axis=1) & np.isfinite(y)
    keep = np.zeros(len(df), bool)
    keep[::STEP] = True
    keep &= ok
    m = _fit_calibrated(X.to_numpy()[keep], y[keep], df.index[keep], pd.Timedelta(minutes=15 * HORIZON))
    base, iso = (m.m, m.iso) if isinstance(m, _Calibrated) else (m, None)
    sc, lr = base.named_steps["standardscaler"], base.named_steps["logisticregression"]
    clim = pd.Series(y[keep]).groupby(_how(df.index[keep])).mean()
    return {"features": list(FEATURES), "mean": sc.mean_.round(6).tolist(), "scale": sc.scale_.round(6).tolist(),
            "coef": lr.coef_[0].round(6).tolist(), "intercept": round(float(lr.intercept_[0]), 6),
            "iso_x": iso.X_thresholds_.round(6).tolist() if iso is not None else None,
            "iso_y": iso.y_thresholds_.round(6).tolist() if iso is not None else None,
            "usual": {str(int(k)): round(float(v), 4) for k, v in clim.items()}, "base_rate": round(float(y[keep].mean()), 4),
            "fitted_until": str(df.index[-1]), "target_pct": TARGET * 100, "hours": HORIZON / 4,
            "skill": report.get("skill"), "holdout_skill": report.get("holdout_skill"),
            "skill_ci99": report.get("skill_ci99"), "period": report.get("period"), "qualified": report.get("qualified"),
            "calibrated_bins": calibrated_bins(report)}


def calibrated_bins(report: dict) -> Optional[list]:
    """Probability ranges where the out-of-sample check actually tested calibration (>= 300 predictions, within 5
    points). Approval rule 3 ignores sparse bins by design; a number falling in one of them was never shown to be
    reliable, so it is not displayed. Display rule only: the approval rules are unchanged. None = no table."""
    if not report.get("calibration"):
        return None
    out = []
    for c in report.get("calibration") or []:
        try:
            lo, hi = (float(x) / 100 for x in c["bin"].rstrip("%").split("-"))
        except (KeyError, ValueError):
            continue
        if c.get("n", 0) >= 300 and abs(c["predicted"] - c["actual"]) <= 0.05:
            out.append([lo, 1.01 if hi >= 1.0 else hi])
    return out


def predict(params: dict, recent: pd.DataFrame) -> Optional[dict]:
    """P(move >= TARGET either way within 4 h) for the last closed bar, from exported parameters.
    None when the model is not qualified, data are short, or the probability falls outside the calibrated ranges."""
    if not params or not params.get("qualified") or len(recent) < 400:
        return None
    f = features(recent).iloc[-1][params["features"]].to_numpy(float)
    if not np.isfinite(f).all():
        return None
    z = (f - np.asarray(params["mean"])) / np.asarray(params["scale"])
    p = 1 / (1 + np.exp(-(float(z @ np.asarray(params["coef"])) + params["intercept"])))
    if params.get("iso_x"):
        p = float(np.interp(p, params["iso_x"], params["iso_y"]))
    bins = params.get("calibrated_bins")
    if bins is not None and not any(lo <= p < hi for lo, hi in bins):
        return None
    usual = params["usual"].get(str(int(_how(recent.index[-1:])[0])), params["base_rate"])
    return {"probability": round(float(p), 3), "usual": round(float(usual), 3)}


# ---------------------------------------------------------------- HAR challenger (pre-registered 2026-11-15)
HAR_DOC = """HAR challenger: the same target, folds, calibration and holdout as the current model, but the inputs are only the
three classic HAR components of realised volatility (last 4 h, last day, last week of 15-min returns, in logs) plus
hour of day. The current model is replaced ONLY if HAR's out-of-sample Brier score is better with a 99 % day-block
bootstrap CI above zero AND it is also better on the final holdout."""
HAR_FEATURES = ("har4h", "har1d", "har1w", "hsin", "hcos")
_base_features = features


def har_features(df: pd.DataFrame) -> pd.DataFrame:
    r2 = np.log(df["close"]).diff() ** 2
    f = pd.DataFrame(index=df.index)
    f["har4h"] = np.log(r2.rolling(16, min_periods=12).mean() + 1e-10)
    f["har1d"] = np.log(r2.rolling(96, min_periods=72).mean() + 1e-10)
    f["har1w"] = np.log(r2.rolling(672, min_periods=400).mean() + 1e-10)
    base = _base_features(df)
    f["hsin"], f["hcos"] = base["hsin"], base["hcos"]
    return f


def compare_har(df: pd.DataFrame) -> dict:
    """Run current vs HAR on identical rows and folds; return both skills and the paired difference CI."""
    cur = evaluate(df, return_preds=True)
    orig, orig_cols = features, FEATURES
    try:
        globals()["features"] = har_features
        globals()["FEATURES"] = HAR_FEATURES
        har = evaluate(df, return_preds=True)
    finally:
        globals()["features"], globals()["FEATURES"] = orig, orig_cols
    a, b = cur.pop("preds"), har.pop("preds")
    j = a.join(b, lsuffix="_cur", rsuffix="_har", how="inner")
    y = pd.Series(labels(df), index=df.index).reindex(j.index).to_numpy()
    ok = np.isfinite(y)
    j, y = j[ok], y[ok]
    e_cur, e_har = (j["p_cur"].to_numpy() - y) ** 2, (j["p_har"].to_numpy() - y) ** 2
    d = e_cur - e_har  # > 0: HAR better
    day = j.index.floor("D").asi8
    u, inv = np.unique(day, return_inverse=True)
    s, cnt = np.bincount(inv, d, len(u)), np.bincount(inv, None, len(u))
    rng = np.random.default_rng(4)
    boots = [s[k].sum() / cnt[k].sum() for k in (rng.integers(0, len(u), len(u)) for _ in range(2000))]
    ci = [float(np.percentile(boots, 0.5)), float(np.percentile(boots, 99.5))]
    cut = j.index[int(len(j) * (1 - HOLDOUT_FRAC))]
    ho = j.index >= cut
    return {"current_skill": cur.get("skill"), "har_skill": har.get("skill"), "current_qualified": cur.get("qualified"),
            "har_qualified": har.get("qualified"), "brier_current": round(float(e_cur.mean()), 5),
            "brier_har": round(float(e_har.mean()), 5), "har_better_ci99": [round(ci[0], 6), round(ci[1], 6)],
            "holdout_brier_current": round(float(e_cur[ho].mean()), 5), "holdout_brier_har": round(float(e_har[ho].mean()), 5),
            "replace": bool(ci[0] > 0 and e_har[ho].mean() < e_cur[ho].mean())}
