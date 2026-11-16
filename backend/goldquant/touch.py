"""Touch probability: will the price REACH a given level within the next T hours?

Why this can work when direction does not: reaching a level is mostly a matter of distance and of how much the market
is moving, and volatility IS predictable (it clusters; see activity.py, validated for BTC / SOL). The model is still
allowed to find directional information (side x recent return); the validation decides whether any of it is real.

PRE-REGISTERED 2026-11-16, before any result was seen. One attempt per asset and horizon; nothing below is tuned
after looking at results. If an asset / horizon fails, it is not shown, and the rules are not changed to make it pass.

  data      hourly bars (crypto: Binance archive; gold: Dukascopy), one origin every STRIDE hours
  targets   for every origin, levels UP and DOWN at d x ATR(14, H1) from the close, d in DIST[horizon]
  label     1 if the high (UP) / low (DOWN) of bars t+1 .. t+H reaches the level, else 0
  horizons  H = 4, 24 and 120 hours (120 h = one trading week for gold)
  features  log d, (log d)^2, side, side x 24h return / ATR, side x 120h return / ATR, log realised vol 4h / 24h /
            7d relative to ATR, log ATR/close vs its 30-day median, hour-of-week (sin, cos), weekend flag
  model     logistic regression fitted on the training data minus its last 12 months, then an isotonic recalibration
            learned on those last 12 months (both strictly before the test period) — the method that passed in
            activity.py, declared here up front instead of as a second attempt
  baseline  hit rate for the same horizon, side and distance learned on the same training data ("distance only") —
            the honest competitor: a model that cannot beat it adds nothing
  folds     calendar years from first_year, expanding window, purge = H hours; the last 20 % of time is a final
            holdout never used to choose anything
  qualifies only if ALL hold (per asset and horizon; 4 assets x 3 horizons = 12 tests, hence the 99.9 % CI):
    1. Brier skill vs baseline over all out-of-sample predictions, 99.9 % block bootstrap CI above zero (blocks of
       max(1 day, H): overlapping labels of one block are resampled together)
    2. skill positive in every fold and in the final holdout
    3. calibrated: in every probability bin with >= 300 predictions, |predicted - actual| <= 5 points
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

HORIZONS = (4, 24, 120)
DIST = {4: (0.5, 1.0, 1.5, 2.0, 3.0, 4.0), 24: (1.0, 2.0, 3.0, 4.0, 6.0, 8.0), 120: (2.0, 4.0, 6.0, 8.0, 12.0, 16.0)}
STRIDE = {4: 2, 24: 4, 120: 12}
HOLDOUT_FRAC = 0.2
CI_LEVEL = 99.9
BINS = (0.0, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.01)
CAL_MONTHS = 12
FEATURES = ("ld", "ld2", "side", "s_r24", "s_r120", "rv4", "rv24", "rv168", "atrz", "hsin", "hcos", "wkend")


def _atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    h, lo, c = (df[x].to_numpy(float) for x in ("high", "low", "close"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - lo, np.maximum(np.abs(h - pc), np.abs(lo - pc)))
    return pd.Series(tr).rolling(n).mean().to_numpy()


def origin_features(df: pd.DataFrame) -> pd.DataFrame:
    """Per-hour features known at the close of each bar (no look-ahead)."""
    c = df["close"]
    atr = pd.Series(_atr(df), index=df.index)
    r = np.log(c).diff()
    f = pd.DataFrame(index=df.index)
    f["atr"] = atr
    f["r24"] = (c - c.shift(24)) / atr
    f["r120"] = (c - c.shift(120)) / atr
    for w, k in ((4, "rv4"), (24, "rv24"), (168, "rv168")):
        f[k] = np.log(r.rolling(w, min_periods=w // 2).std() * c / atr + 1e-6)
    lat = np.log(atr / c)
    f["atrz"] = lat - lat.rolling(720, min_periods=240).median()
    close_t = df.index + pd.Timedelta(hours=1)
    how = close_t.dayofweek * 24 + close_t.hour
    f["hsin"] = np.sin(2 * np.pi * how / 168)
    f["hcos"] = np.cos(2 * np.pi * how / 168)
    f["wkend"] = (close_t.dayofweek >= 5).astype(float)
    return f


def samples(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Rows = (origin, side, distance) with label and features. Origins need a full future window."""
    df = df.dropna(subset=["open", "high", "low", "close"])
    of = origin_features(df)
    h, lo, c = (df[x].to_numpy(float) for x in ("high", "low", "close"))
    n = len(c)
    from numpy.lib.stride_tricks import sliding_window_view as win
    idx = np.arange(200, n - horizon - 1, STRIDE[horizon])
    ok = np.isfinite(of["atr"].to_numpy()[idx]) & np.isfinite(of[["r24", "r120", "rv4", "rv24", "rv168", "atrz"]]
                                                                 .to_numpy()[idx]).all(axis=1)
    idx = idx[ok]
    fh = win(h[1:], horizon)[idx].max(axis=1)
    fl = win(lo[1:], horizon)[idx].min(axis=1)
    atr = of["atr"].to_numpy()[idx]
    base = of.iloc[idx]
    rows = []
    for side in (1, -1):
        reach = (fh - c[idx]) / atr if side == 1 else (c[idx] - fl) / atr
        for d in DIST[horizon]:
            x = pd.DataFrame({"t": base.index, "side": float(side), "d": d,
                              "y": (reach >= d).astype(float)})
            for k in ("r24", "r120", "rv4", "rv24", "rv168", "atrz", "hsin", "hcos", "wkend"):
                x[k] = base[k].to_numpy()
            rows.append(x)
    s = pd.concat(rows, ignore_index=True)
    s["ld"] = np.log(s["d"])
    s["ld2"] = s["ld"] ** 2
    s["s_r24"] = s["side"] * s["r24"]
    s["s_r120"] = s["side"] * s["r120"]
    return s.sort_values("t", kind="stable").reset_index(drop=True)


def _fit_calibrated(tr: pd.DataFrame, cal_from: pd.Timestamp):
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    a, b = tr[tr["t"] < cal_from], tr[tr["t"] >= cal_from]
    if len(a) < 2000 or len(b) < 500:
        return None
    sc = StandardScaler().fit(a[list(FEATURES)])
    lr = LogisticRegression(max_iter=500, C=1.0).fit(sc.transform(a[list(FEATURES)]), a["y"])
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(
        lr.predict_proba(sc.transform(b[list(FEATURES)]))[:, 1], b["y"])
    return sc, lr, iso


def _predict(m, X: pd.DataFrame) -> np.ndarray:
    sc, lr, iso = m
    return iso.predict(lr.predict_proba(sc.transform(X[list(FEATURES)]))[:, 1])


def _baseline(tr: pd.DataFrame, te: pd.DataFrame) -> np.ndarray:
    rate = tr.groupby(["side", "d"])["y"].mean()
    return np.array([rate.get((s, d), tr["y"].mean()) for s, d in zip(te["side"], te["d"])])


def _ci(day: np.ndarray, e_m: np.ndarray, e_b: np.ndarray, level: float, n_boot: int = 2000, seed: int = 7):
    u, inv = np.unique(day, return_inverse=True)
    sm, sb = np.bincount(inv, e_m, len(u)), np.bincount(inv, e_b, len(u))
    rng = np.random.default_rng(seed)
    k = rng.integers(0, len(u), (n_boot, len(u)))
    s = 1 - sm[k].sum(1) / sb[k].sum(1)
    q = (100 - level) / 2
    return [round(float(np.percentile(s, q)), 4), round(float(np.percentile(s, 100 - q)), 4)]


def evaluate(df: pd.DataFrame, horizon: int, first_year: int = 2022) -> dict:
    s = samples(df, horizon)
    t = pd.DatetimeIndex(s["t"])
    t0, t1 = t.min(), t.max()
    cut = t0 + (t1 - t0) * (1 - HOLDOUT_FRAC)
    gap = pd.Timedelta(hours=horizon)
    bounds = [b for b in (pd.Timestamp(f"{y}-01-01", tz="UTC") for y in range(first_year, t1.year + 1)) if b < cut]
    bounds = bounds + [cut, t1 + pd.Timedelta(hours=1)]
    P, B, Y, T, folds = [], [], [], [], []
    for a, b in zip(bounds[:-1], bounds[1:]):
        tr = s[t < a - gap]
        te = s[(t >= a) & (t < b)]
        if len(te) == 0:
            continue
        m = _fit_calibrated(tr, a - gap - pd.DateOffset(months=CAL_MONTHS))
        if m is None:
            continue
        p, base = _predict(m, te), _baseline(tr, te)
        y = te["y"].to_numpy()
        skill = 1 - np.mean((p - y) ** 2) / np.mean((base - y) ** 2)
        folds.append({"from": str(a.date()), "n": int(len(te)), "skill": round(float(skill), 4),
                      "holdout": bool(a == cut)})
        blk = pd.Timedelta(hours=max(24, horizon)).value
        # nanoseconds explicitly: bar indexes may be microsecond-resolution, and asi8 follows the index unit
        P.append(p); B.append(base); Y.append(y); T.append(pd.DatetimeIndex(te["t"]).as_unit("ns").asi8 // blk)
    if not folds:
        return {"horizon": horizon, "qualified": False, "reason": "not enough data"}
    p, base, y, day = (np.concatenate(x) for x in (P, B, Y, T))
    e_m, e_b = (p - y) ** 2, (base - y) ** 2
    skill = 1 - e_m.sum() / e_b.sum()
    ci = _ci(day, e_m, e_b, CI_LEVEL)
    cal = []
    for lo_, hi_ in zip(BINS[:-1], BINS[1:]):
        k = (p >= lo_) & (p < hi_)
        if k.sum():
            cal.append({"bin": f"{int(lo_ * 100)}-{int(min(hi_, 1) * 100)}%", "n": int(k.sum()),
                        "predicted": round(float(p[k].mean()), 4), "actual": round(float(y[k].mean()), 4)})
    hold = next((f for f in folds if f["holdout"]), None)
    rules = {"ci_above_zero": ci[0] > 0,
             "every_fold_positive": all(f["skill"] > 0 for f in folds),
             "holdout_positive": bool(hold and hold["skill"] > 0),
             "calibrated": all(abs(c["predicted"] - c["actual"]) <= 0.05 for c in cal if c["n"] >= 300)}
    return {"horizon": horizon, "skill": round(float(skill), 4), f"skill_ci{CI_LEVEL:g}": ci,
            "holdout_skill": hold["skill"] if hold else None, "folds": folds, "calibration": cal,
            "base_rate": round(float(y.mean()), 4), "n": int(len(y)), "rules": rules,
            "qualified": all(rules.values()),
            "reason": "passed" if all(rules.values()) else "failed: " + ", ".join(k for k, v in rules.items() if not v),
            "period": f"{t0.date()} -> {t1.date()}"}


def evaluate_asset(h1: pd.DataFrame, first_year: int = 2022) -> dict:
    return {str(h): evaluate(h1, h, first_year) for h in HORIZONS}


def export(h1: pd.DataFrame, horizon: int) -> Optional[dict]:
    """Final model on all history (only called for a qualified asset / horizon)."""
    s = samples(h1, horizon)
    t = pd.DatetimeIndex(s["t"])
    m = _fit_calibrated(s, t.max() - pd.DateOffset(months=CAL_MONTHS))
    if m is None:
        return None
    sc, lr, iso = m
    return {"features": list(FEATURES), "mean": sc.mean_.tolist(), "scale": sc.scale_.tolist(),
            "coef": lr.coef_[0].tolist(), "intercept": float(lr.intercept_[0]),
            "iso_x": iso.X_thresholds_.tolist(), "iso_y": iso.y_thresholds_.tolist(),
            "dist_range": [min(DIST[horizon]), max(DIST[horizon])]}
