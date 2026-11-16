"""Price-range engine (research): an 80 % interval for the CLOSE price H hours ahead. Never a buy/sell signal.

PRE-REGISTERED 2026-11-16, committed before any result on real data was seen. One attempt per asset and horizon;
nothing below is tuned on the results. Assets are tested separately (BTC, ETH, SOL, XAU).

Target   r = ln(close[t+H] / close[t]) — the close only. The high/low inside the window is a different question
         (see touch.py) and is not used or claimed here.
Horizons crypto (24/7, hourly bars): 4, 24, 168 bars. Gold (hourly bars exist only while the market trades, so a
         horizon counts trading hours and the weekend is not "time"): 4, 23 (one trading day), 115 (one trading week).
Origins  every 4 bars for the 4 h and 1 day horizons, every day (24 / 23 bars) for the week.
Model    HAR scale model: log(future realised variance over H) regressed (OLS) on log realised variance over the
         last 4 bars, 1 day, 1 week and 4 weeks (+ hour-of-day sin/cos for H = 4; + weekend flag for crypto).
         Interval = [q10 * s, q90 * s] where s = exp(prediction / 2) and q10 / q90 are the empirical quantiles of
         r / s on a calibration window (the last 12 months of the training data). The scale model is fitted only on
         origins whose outcome was known before that calibration window (no leakage into the calibration).
Baselines (the candidate must beat the BETTER of the two):
         B1 historical: 10 % / 90 % quantiles of the H-returns completed in the last 365 days (known at t).
         B2 recent volatility: EWMA (lambda 0.94) of hourly squared returns, +/- 1.2816 * sigma * sqrt(H).
Score    interval score (Gneiting & Raftery 2007), alpha = 0.2: width + 10 * (amount by which the close fell outside).
         Lower is better. Reported in percent of price, with coverage and mean width.
Walk-forward: calendar-year folds from the third year of data; each fold trains on origins whose outcome was known
         before the fold starts (purge = H). The last 20 % of time is a holdout used once, trained on everything known
         before it.
Qualifies (asset x horizon) only if ALL hold:
  G1 holdout coverage between 77 % and 83 %
  G2 walk-forward: mean interval score below the better baseline, 99 % block-bootstrap CI of the difference entirely
     below zero (blocks of whole days, at least the horizon long — overlapping windows are not independent)
  G3 holdout: mean interval score below the better baseline's
  G4 walk-forward coverage >= 72 % in each volatility tercile (low / mid / high trailing-week volatility)
Descriptive only (not a gate): coverage and score in windows that contain a scheduled US event (FOMC decisions and
BLS releases, where their dates are available); median width vs baselines.
If an asset / horizon fails, it stays experimental and is never shown as a validated feature.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

VERSION = "range-har-0.1.0"
ALPHA = 0.2
Z90 = 1.2816
COVER_LO, COVER_HI, REGIME_MIN = 0.77, 0.83, 0.72
CI_LEVEL = 99.0
HOLDOUT_FRAC = 0.2
CAL_MONTHS = 12
LAMBDA = 0.94
HORIZONS = {"crypto": {"4h": 4, "24h": 24, "1w": 168}, "gold": {"4h": 4, "24h": 23, "1w": 115}}
STEPS = {"crypto": {"4h": 4, "24h": 4, "1w": 24}, "gold": {"4h": 4, "24h": 4, "1w": 23}}
WINDOWS = {"crypto": (4, 24, 168, 672), "gold": (4, 23, 115, 460)}
HIST_BARS = {"crypto": 24 * 365, "gold": 23 * 5 * 52}


def interval_score(lo: np.ndarray, hi: np.ndarray, y: np.ndarray, alpha: float = ALPHA) -> np.ndarray:
    return (hi - lo) + (2 / alpha) * np.maximum(lo - y, 0) + (2 / alpha) * np.maximum(y - hi, 0)


def frame(h1: pd.DataFrame, kind: str, H: int) -> pd.DataFrame:
    """Per-bar table: label, features, baselines. Index = bar open time; the decision is taken at its close."""
    c = h1["close"].astype(float)
    lr = np.log(c).diff()
    r2 = lr ** 2
    w4, wd, ww, wm = WINDOWS[kind]
    out = pd.DataFrame(index=h1.index)
    out["t"] = h1.index + pd.Timedelta(hours=1)  # decision time = bar close
    out["y"] = np.log(c.shift(-H) / c) * 100  # percent log return to the close H bars ahead
    out["known"] = out["t"].shift(-H)  # when the outcome is known
    fut = r2[::-1].rolling(H, min_periods=H).sum()[::-1].shift(-1)  # sum of r^2 over the next H bars
    out["ly"] = np.log(fut * 1e4 + 1e-6)
    for k, w in (("rv4", w4), ("rvd", wd), ("rvw", ww), ("rvm", wm)):
        out[k] = np.log(r2.rolling(w, min_periods=max(2, w // 2)).sum() * 1e4 * H / w + 1e-6)
    hr = out["t"].dt.hour
    out["hs"], out["hc"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    out["wk"] = (out["t"].dt.dayofweek >= 5).astype(float)
    # B2: EWMA of hourly squared returns, known at the close of the bar
    ew = r2.ewm(alpha=1 - LAMBDA, adjust=False).mean()
    s2 = np.sqrt(ew * H) * 100
    out["b2_lo"], out["b2_hi"] = -Z90 * s2, Z90 * s2
    # B1: 10 / 90 % of the H-returns completed by t (origin j completes at j + H <= t), trailing 365 days
    done = out["y"].shift(H)
    roll = done.rolling(HIST_BARS[kind], min_periods=HIST_BARS[kind] // 4)
    out["b1_lo"], out["b1_hi"] = roll.quantile(0.1), roll.quantile(0.9)
    return out


def _features(kind: str, H: int) -> list:
    f = ["rv4", "rvd", "rvw", "rvm"]
    if H == 4:
        f += ["hs", "hc"]
    if kind == "crypto":
        f += ["wk"]
    return f


def _fit(train: pd.DataFrame, cols: list, cal_start: pd.Timestamp):
    """Scale model on origins known before the calibration window, z-quantiles on the calibration window."""
    fit = train[train["known"] < cal_start].dropna(subset=cols + ["ly", "y"])
    cal = train[train["t"] >= cal_start].dropna(subset=cols + ["y"])
    if len(fit) < 500 or len(cal) < 200:
        return None
    X = np.column_stack([np.ones(len(fit))] + [fit[c].to_numpy() for c in cols])
    beta, *_ = np.linalg.lstsq(X, fit["ly"].to_numpy(), rcond=None)
    s = _scale(cal, cols, beta)
    z = cal["y"].to_numpy() / s
    return beta, float(np.quantile(z, 0.1)), float(np.quantile(z, 0.9))


def _scale(d: pd.DataFrame, cols: list, beta: np.ndarray) -> np.ndarray:
    X = np.column_stack([np.ones(len(d))] + [d[c].to_numpy() for c in cols])
    return np.exp(X @ beta / 2)


def _predict(d: pd.DataFrame, cols: list, m) -> tuple:
    beta, q10, q90 = m
    s = _scale(d, cols, beta)
    return q10 * s, q90 * s


def _ci(t: pd.Series, diff: np.ndarray, block_days: int, level: float = CI_LEVEL, n_boot: int = 2000, seed: int = 11):
    blk = pd.DatetimeIndex(t).as_unit("ns").asi8 // (block_days * 86_400 * 10**9)
    ids, inv = np.unique(blk, return_inverse=True)
    sums = np.bincount(inv, weights=diff)
    cnt = np.bincount(inv)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(ids), size=(n_boot, len(ids)))
    boot = sums[draws].sum(axis=1) / cnt[draws].sum(axis=1)
    a = (100 - level) / 2
    return float(np.percentile(boot, a)), float(np.percentile(boot, 100 - a))


def _stats(lo, hi, y) -> dict:
    inside = (y >= lo) & (y <= hi)
    return {"n": int(len(y)), "coverage": round(float(inside.mean()), 4), "width_pct": round(float(np.mean(hi - lo)), 4),
            "median_width_pct": round(float(np.median(hi - lo)), 4),
            "interval_score": round(float(np.mean(interval_score(lo, hi, y))), 4)}


def evaluate(h1: pd.DataFrame, kind: str, name: str, events: Optional[list] = None) -> dict:
    H, step = HORIZONS[kind][name], STEPS[kind][name]
    cols = _features(kind, H)
    df = frame(h1.dropna(subset=["close"]), kind, H)
    df = df.iloc[::step].dropna(subset=["y", "known", "b1_lo", "b2_lo"])
    rep = {"version": VERSION, "horizon": name, "bars": H, "qualified": False}
    if len(df) < 2000:
        rep["reason"] = "not enough history"
        return rep
    t = df["t"]
    cut = t.iloc[int(len(df) * (1 - HOLDOUT_FRAC))]
    years = sorted(set(t[t < cut].dt.year))[2:]
    parts = []
    for yr in years:
        y0 = pd.Timestamp(f"{yr}-01-01", tz="UTC")
        te = df[(t >= y0) & (t < min(pd.Timestamp(f"{yr + 1}-01-01", tz="UTC"), cut))]
        tr = df[df["known"] < y0]
        if te.empty:
            continue
        m = _fit(tr, cols, y0 - pd.DateOffset(months=CAL_MONTHS))
        if m is None:
            continue
        lo, hi = _predict(te, cols, m)
        parts.append(te.assign(m_lo=lo, m_hi=hi, fold=yr))
    if not parts:
        rep["reason"] = "no complete fold"
        return rep
    wf = pd.concat(parts)
    tr = df[df["known"] < cut]
    ho = df[t >= cut]
    m = _fit(tr, cols, cut - pd.DateOffset(months=CAL_MONTHS))
    if m is None or ho.empty:
        rep["reason"] = "holdout could not be fitted"
        return rep
    lo, hi = _predict(ho, cols, m)
    ho = ho.assign(m_lo=lo, m_hi=hi)

    def block(d: pd.DataFrame) -> dict:
        y = d["y"].to_numpy()
        out = {k: _stats(d[f"{k}_lo"].to_numpy(), d[f"{k}_hi"].to_numpy(), y) for k in ("m", "b1", "b2")}
        out["best_baseline"] = "b1" if out["b1"]["interval_score"] <= out["b2"]["interval_score"] else "b2"
        return out

    W, Ho = block(wf), block(ho)
    best = W["best_baseline"]
    diff = (interval_score(wf["m_lo"].to_numpy(), wf["m_hi"].to_numpy(), wf["y"].to_numpy())
            - interval_score(wf[f"{best}_lo"].to_numpy(), wf[f"{best}_hi"].to_numpy(), wf["y"].to_numpy()))
    ci = _ci(wf["t"], diff, max(1, int(np.ceil(H / 24))))
    # volatility terciles of the trailing week (descriptive bins on the out-of-sample set)
    q = wf["rvw"].quantile([1 / 3, 2 / 3]).to_numpy()
    reg = np.where(wf["rvw"] <= q[0], "low", np.where(wf["rvw"] <= q[1], "mid", "high"))
    regimes = {}
    for g in ("low", "mid", "high"):
        d = wf[reg == g]
        regimes[g] = {k: _stats(d[f"{k}_lo"].to_numpy(), d[f"{k}_hi"].to_numpy(), d["y"].to_numpy()) for k in ("m", "b1", "b2")}
    folds = {}
    for yr, d in wf.groupby("fold"):
        folds[str(yr)] = {k: _stats(d[f"{k}_lo"].to_numpy(), d[f"{k}_hi"].to_numpy(), d["y"].to_numpy()) for k in ("m", best)}
    ev = None
    if events:
        et = np.array(sorted(pd.to_datetime(events, utc=True).as_unit("ns").asi8))
        allp = pd.concat([wf, ho])
        t0 = pd.DatetimeIndex(allp["t"]).as_unit("ns").asi8
        t1 = pd.DatetimeIndex(allp["known"]).as_unit("ns").asi8
        k = np.searchsorted(et, t0, side="right")
        hit = (k < len(et)) & (et[np.minimum(k, len(et) - 1)] <= t1)
        d = allp[hit]
        if len(d):
            ev = {"windows": int(len(d)), "first": str(pd.Timestamp(et[0])), "last": str(pd.Timestamp(et[-1])),
                  **{k2: _stats(d[f"{k2}_lo"].to_numpy(), d[f"{k2}_hi"].to_numpy(), d["y"].to_numpy()) for k2 in ("m", "b1", "b2")}}
    g1 = COVER_LO <= Ho["m"]["coverage"] <= COVER_HI
    g2 = W["m"]["interval_score"] < W[best]["interval_score"] and ci[1] < 0
    g3 = Ho["m"]["interval_score"] < Ho[Ho["best_baseline"]]["interval_score"]
    g4 = all(regimes[g]["m"]["coverage"] >= REGIME_MIN for g in regimes)
    rep.update({
        "period": f"{t.iloc[0].date()} -> {t.iloc[-1].date()}", "holdout_from": str(cut.date()),
        "walk_forward": W, "holdout": Ho, "score_diff_vs_best": round(float(diff.mean()), 4),
        f"score_diff_ci{CI_LEVEL:g}": [round(ci[0], 4), round(ci[1], 4)], "regimes": regimes, "folds": folds,
        "events": ev, "calibration_quantiles": [round(m[1], 3), round(m[2], 3)],
        "gates": {"G1 holdout coverage 77-83%": g1, "G2 beats best baseline (99% CI)": g2,
                  "G3 holdout beats best baseline": g3, "G4 coverage >= 72% in every volatility tercile": g4},
    })
    rep["qualified"] = bool(g1 and g2 and g3 and g4)
    rep["reason"] = "qualified" if rep["qualified"] else "failed: " + ", ".join(k for k, v in rep["gates"].items() if not v)
    return rep


def evaluate_asset(h1: pd.DataFrame, kind: str, events: Optional[list] = None) -> dict:
    return {name: evaluate(h1, kind, name, events) for name in HORIZONS[kind]}


# ---------------------------------------------------------------- export + live (same model as validated, all data)
def export(h1: pd.DataFrame, kind: str, name: str) -> Optional[dict]:
    """Scale model + calibration quantiles fitted on all history (calibration = its last CAL_MONTHS)."""
    H, step = HORIZONS[kind][name], STEPS[kind][name]
    cols = _features(kind, H)
    df = frame(h1.dropna(subset=["close"]), kind, H).iloc[::step].dropna(subset=["y", "known"])
    if len(df) < 2000:
        return None
    m = _fit(df, cols, df["t"].iloc[-1] - pd.DateOffset(months=CAL_MONTHS))
    if m is None:
        return None
    beta, q10, q90 = m
    return {"version": VERSION, "kind": kind, "horizon": name, "bars": H, "cols": cols,
            "beta": [float(b) for b in beta], "q10": q10, "q90": q90, "trained_until": str(df["t"].iloc[-1])}


def live(params: dict, h1: pd.DataFrame, now: Optional[pd.Timestamp] = None) -> Optional[dict]:
    """80 % interval for the close `bars` hourly bars after the last CLOSED bar. None without enough data."""
    if not params or h1 is None:
        return None
    d = h1.dropna(subset=["close"])
    if now is not None:
        d = d[d.index + pd.Timedelta(hours=1) <= now]  # only closed bars
    kind, H = params["kind"], int(params["bars"])
    if len(d) < WINDOWS[kind][-1] + 5:
        return None
    f = frame(d, kind, H).iloc[-1]
    cols = params["cols"]
    if any(not np.isfinite(f[c]) for c in cols):
        return None
    x = np.array([1.0] + [float(f[c]) for c in cols])
    s = float(np.exp(x @ np.array(params["beta"]) / 2))
    c = float(d["close"].iloc[-1])
    lo, hi = params["q10"] * s, params["q90"] * s
    return {"horizon": params["horizon"], "bars": H, "issued_at": str(f["t"]), "close_at_issue": c,
            "low": c * float(np.exp(lo / 100)), "high": c * float(np.exp(hi / 100)),
            "lo_pct": round(lo, 4), "hi_pct": round(hi, 4), "version": params["version"]}


def display_horizon(qualified: dict) -> Optional[str]:
    """The strip shows the day horizon when it qualified, else 4 h; None when neither did."""
    for h in ("24h", "4h"):
        if qualified.get(h):
            return h
    return None
