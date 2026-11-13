"""Cross-Market Divergence (V2 #5) and Market Causality as Granger predictive precedence (V2 #1).

Divergence: rolling OLS of gold returns on related-market returns; the z-score of the recent cumulative
residual measures how far gold has moved away from what its usual relationships imply.
Granger tests answer "does X's past improve the prediction of gold beyond gold's own past?" — this is
predictive precedence, NOT proven causality, and results are reported with rolling stability.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def _ols_resid(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    return y - X1 @ beta


def divergence(gold: pd.Series, others: dict[str, pd.Series], window: int = 120, recent: int = 10) -> dict | None:
    """All series are price levels on a shared time index. Uses log returns."""
    df = pd.concat({"gold": gold, **others}, axis=1).dropna()
    r = np.log(df).diff().dropna()
    if len(r) < window + recent + 20:
        return None
    train = r.iloc[-(window + recent):-recent]
    X, y = train[list(others)].to_numpy(), train["gold"].to_numpy()
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    resid_train = y - X1 @ beta
    rec = r.iloc[-recent:]
    pred = np.column_stack([np.ones(recent), rec[list(others)].to_numpy()]) @ beta
    cum_resid = float(np.sum(rec["gold"].to_numpy() - pred))
    sd = float(np.std(resid_train, ddof=1) * np.sqrt(recent))
    z = cum_resid / sd if sd > 0 else 0.0
    corr_long = r.iloc[-(window + recent):].corr()["gold"].drop("gold")
    corr_recent = r.iloc[-recent * 3:].corr()["gold"].drop("gold")
    return {"z_residual": round(z, 3), "betas": {k: round(float(b), 4) for k, b in zip(others, beta[1:])},
            "r2": round(1 - np.var(resid_train) / np.var(y), 3) if np.var(y) > 0 else 0.0,
            "corr_long": corr_long.round(3).to_dict(), "corr_recent": corr_recent.round(3).to_dict(),
            "abnormal": abs(z) >= 2.0}


def granger(y: pd.Series, x: pd.Series, lags: int = 3) -> dict:
    """F-test: restricted y~y_lags vs unrestricted y~y_lags+x_lags. Inputs are stationary series (returns)."""
    df = pd.concat({"y": y, "x": x}, axis=1).dropna()
    cols_r, cols_u = {}, {}
    for k in range(1, lags + 1):
        cols_r[f"y{k}"] = df["y"].shift(k)
        cols_u[f"x{k}"] = df["x"].shift(k)
    D = pd.concat([df["y"], pd.DataFrame(cols_r), pd.DataFrame(cols_u)], axis=1).dropna()
    n = len(D)
    if n < 10 * lags + 20:
        return {"n": n, "F": None, "p": None}
    yv = D["y"].to_numpy()
    rss_r = float(np.sum(_ols_resid(yv, D[list(cols_r)].to_numpy()) ** 2))
    rss_u = float(np.sum(_ols_resid(yv, D[list(cols_r) + list(cols_u)].to_numpy()) ** 2))
    df1, df2 = lags, n - 2 * lags - 1
    F = ((rss_r - rss_u) / df1) / (rss_u / df2)
    return {"n": n, "F": round(F, 4), "p": float(stats.f.sf(F, df1, df2))}


def granger_stability(y: pd.Series, x: pd.Series, lags: int = 3, window: int = 250, step: int = 50) -> dict:
    """Share of rolling windows where x Granger-precedes y at 5 % — a relation that flickers is not used."""
    res = []
    for end in range(window, len(y) + 1, step):
        g = granger(y.iloc[end - window:end], x.iloc[end - window:end], lags)
        if g["p"] is not None:
            res.append(g["p"] < 0.05)
    full = granger(y, x, lags)
    return {**full, "windows": len(res), "share_significant": round(float(np.mean(res)), 3) if res else None,
            "label_ar": "أسبقية تنبؤية (Granger) — ليست سببية مثبتة"}
