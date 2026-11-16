"""High / low bounds engine (research): how far ABOVE and BELOW the current price the market is likely to trade within
the next 4 h / 1 day / 1 week. Separate from the closing-range engine (price_range.py), which is not changed.

PRE-REGISTERED 2026-11-16, committed before any result on real data was seen. One attempt per asset and horizon.
Assets separately: XAU (Dukascopy H1, trading hours only), BTC, ETH, SOL (Binance 1h).

Targets (hourly OHLC: an hourly bar's high/low contains every price traded inside it, so no extreme is missed)
  U = 100 * ln(max high of the next H bars / close at t)  >= 0      (how far up it will trade)
  D = 100 * ln(min low  of the next H bars / close at t)  <= 0      (how far down it will trade)
Horizons / origins / walk-forward / holdout / calibration window: exactly as price_range.py (same HORIZONS, STEPS,
  calendar-year folds from the third year, last 20 % holdout, 12-month calibration, purge = H).
Bounds  upper = q90 of U, lower = q10 of D (each side: "exceeded about 1 time in 10"); the whole path stays inside
  [lower, upper] when neither is exceeded (expected roughly 80-85 %; reported, not a gate by itself).
Model   the HAR scale s of price_range.py (fitted on future realised variance), then the empirical 90 % quantile of
  U / s and the 10 % quantile of D / s on the calibration window — one per side, so asymmetry is allowed.
Baselines (the candidate must beat the better one, per side and for the path):
  B1 historical: q90 of U and q10 of D over the last 365 days of completed windows (known at t).
  B2 volatility: reflection principle for a driftless random walk, +/- 1.645 * sigma_EWMA(0.94) * sqrt(H).
Scores  per side: pinball (quantile) loss at 0.9 for U and 0.1 for D — rewards bounds that are tight AND rarely broken.
  Path: width + 10 * (max(U - upper, 0) + max(lower - D, 0))  (interval score of the whole path, alpha = 0.2).
Qualifies (asset x horizon) only if ALL hold:
  H1 holdout: each side exceeded between 7 % and 13 % of the time
  H2 walk-forward: pinball loss better than the better baseline for BOTH sides, each 99 % block-bootstrap CI of the
     difference entirely below zero (blocks of whole days, at least the horizon long)
  H3 walk-forward: path score better than the better baseline, 99 % CI below zero
  H4 holdout: path score better than the better baseline
  H5 walk-forward: each side exceeded at most 15 % of the time in each volatility tercile
Touching a given support / resistance is the separate, already validated touch engine (touch.py). Which bound is
reached first is a later, separately pre-registered path test. Nothing here is a target, a stop or a signal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import price_range as PR

VERSION = "hilo-har-0.1.0"
QU, QD = 0.9, 0.1
Z95 = 1.6449
EXC_LO, EXC_HI, EXC_REGIME = 0.07, 0.13, 0.15


def pinball(q: np.ndarray, y: np.ndarray, tau: float) -> np.ndarray:
    d = y - q
    return np.maximum(tau * d, (tau - 1) * d)


def path_score(lo, hi, D, U, alpha=0.2):
    return (hi - lo) + (2 / alpha) * (np.maximum(U - hi, 0) + np.maximum(lo - D, 0))


def frame(h1: pd.DataFrame, kind: str, H: int) -> pd.DataFrame:
    f = PR.frame(h1, kind, H)
    c = h1["close"].astype(float)
    hi = h1["high"].astype(float)[::-1].rolling(H, min_periods=H).max()[::-1].shift(-1)
    lo = h1["low"].astype(float)[::-1].rolling(H, min_periods=H).min()[::-1].shift(-1)
    f["U"] = 100 * np.log(hi / c)
    f["D"] = 100 * np.log(lo / c)
    # B1: 90 % / 10 % of the windows completed by t (window j completes at j + H), trailing 365 days
    roll = PR.HIST_BARS[kind]
    f["b1_hi"] = f["U"].shift(H).rolling(roll, min_periods=roll // 4).quantile(QU)
    f["b1_lo"] = f["D"].shift(H).rolling(roll, min_periods=roll // 4).quantile(QD)
    s = (f["b2_hi"] / PR.Z90)  # sigma * sqrt(H) in percent, from price_range's EWMA baseline
    f["b2_hi"], f["b2_lo"] = Z95 * s, -Z95 * s
    return f


def _fit(train: pd.DataFrame, cols: list, cal_start):
    fit = train[train["known"] < cal_start].dropna(subset=cols + ["ly", "U", "D"])
    cal = train[train["t"] >= cal_start].dropna(subset=cols + ["U", "D"])
    if len(fit) < 500 or len(cal) < 200:
        return None
    X = np.column_stack([np.ones(len(fit))] + [fit[c].to_numpy() for c in cols])
    beta, *_ = np.linalg.lstsq(X, fit["ly"].to_numpy(), rcond=None)
    s = PR._scale(cal, cols, beta)
    return beta, float(np.quantile(cal["U"].to_numpy() / s, QU)), float(np.quantile(cal["D"].to_numpy() / s, QD))


def _predict(d, cols, m):
    beta, qu, qd = m
    s = PR._scale(d, cols, beta)
    return qd * s, qu * s


def _stats(lo, hi, D, U) -> dict:
    return {"n": int(len(U)), "upper_exceeded": round(float((U > hi).mean()), 4),
            "lower_exceeded": round(float((D < lo).mean()), 4),
            "path_inside": round(float(((U <= hi) & (D >= lo)).mean()), 4),
            "median_up_pct": round(float(np.median(hi)), 4), "median_down_pct": round(float(np.median(lo)), 4),
            "pinball_up": round(float(np.mean(pinball(hi, U, QU))), 5),
            "pinball_down": round(float(np.mean(pinball(lo, D, QD))), 5),
            "path_score": round(float(np.mean(path_score(lo, hi, D, U))), 4)}


def evaluate(h1: pd.DataFrame, kind: str, name: str) -> dict:
    H, step = PR.HORIZONS[kind][name], PR.STEPS[kind][name]
    cols = PR._features(kind, H)
    df = frame(h1.dropna(subset=["close", "high", "low"]), kind, H)
    df = df.iloc[::step].dropna(subset=["U", "D", "known", "b1_lo", "b2_lo"])
    rep = {"version": VERSION, "horizon": name, "bars": H, "qualified": False}
    if len(df) < 2000:
        rep["reason"] = "not enough history"
        return rep
    t = df["t"]
    cut = t.iloc[int(len(df) * (1 - PR.HOLDOUT_FRAC))]
    parts = []
    for yr in sorted(set(t[t < cut].dt.year))[2:]:
        y0 = pd.Timestamp(f"{yr}-01-01", tz="UTC")
        te = df[(t >= y0) & (t < min(pd.Timestamp(f"{yr + 1}-01-01", tz="UTC"), cut))]
        m = _fit(df[df["known"] < y0], cols, y0 - pd.DateOffset(months=PR.CAL_MONTHS))
        if te.empty or m is None:
            continue
        lo, hi = _predict(te, cols, m)
        parts.append(te.assign(m_lo=lo, m_hi=hi))
    m = _fit(df[df["known"] < cut], cols, cut - pd.DateOffset(months=PR.CAL_MONTHS))
    ho = df[t >= cut]
    if not parts or m is None or ho.empty:
        rep["reason"] = "no complete fold"
        return rep
    wf = pd.concat(parts)
    lo, hi = _predict(ho, cols, m)
    ho = ho.assign(m_lo=lo, m_hi=hi)

    def block(d):
        out = {k: _stats(d[f"{k}_lo"].to_numpy(), d[f"{k}_hi"].to_numpy(), d["D"].to_numpy(), d["U"].to_numpy())
               for k in ("m", "b1", "b2")}
        out["best_up"] = min(("b1", "b2"), key=lambda k: out[k]["pinball_up"])
        out["best_down"] = min(("b1", "b2"), key=lambda k: out[k]["pinball_down"])
        out["best_path"] = min(("b1", "b2"), key=lambda k: out[k]["path_score"])
        return out

    W, Ho = block(wf), block(ho)
    U, D = wf["U"].to_numpy(), wf["D"].to_numpy()
    bd = max(1, int(np.ceil(H / 24)))
    d_up = pinball(wf["m_hi"].to_numpy(), U, QU) - pinball(wf[f"{W['best_up']}_hi"].to_numpy(), U, QU)
    d_dn = pinball(wf["m_lo"].to_numpy(), D, QD) - pinball(wf[f"{W['best_down']}_lo"].to_numpy(), D, QD)
    bp = W["best_path"]
    d_pa = (path_score(wf["m_lo"].to_numpy(), wf["m_hi"].to_numpy(), D, U)
            - path_score(wf[f"{bp}_lo"].to_numpy(), wf[f"{bp}_hi"].to_numpy(), D, U))
    ci_up, ci_dn, ci_pa = (PR._ci(wf["t"], x, bd) for x in (d_up, d_dn, d_pa))
    q = wf["rvw"].quantile([1 / 3, 2 / 3]).to_numpy()
    reg = np.where(wf["rvw"] <= q[0], "low", np.where(wf["rvw"] <= q[1], "mid", "high"))
    regimes = {g: _stats(wf.loc[reg == g, "m_lo"].to_numpy(), wf.loc[reg == g, "m_hi"].to_numpy(),
                         wf.loc[reg == g, "D"].to_numpy(), wf.loc[reg == g, "U"].to_numpy()) for g in ("low", "mid", "high")}
    g = {"H1 holdout each side exceeded 7-13%": EXC_LO <= Ho["m"]["upper_exceeded"] <= EXC_HI
         and EXC_LO <= Ho["m"]["lower_exceeded"] <= EXC_HI,
         "H2 both sides beat best baseline (99% CI)": ci_up[1] < 0 and ci_dn[1] < 0,
         "H3 path score beats best baseline (99% CI)": ci_pa[1] < 0,
         "H4 holdout path score beats best baseline": Ho["m"]["path_score"] < Ho[Ho["best_path"]]["path_score"],
         "H5 each side exceeded <= 15% in every volatility tercile": all(
             r["upper_exceeded"] <= EXC_REGIME and r["lower_exceeded"] <= EXC_REGIME for r in regimes.values())}
    rep.update({"period": f"{t.iloc[0].date()} -> {t.iloc[-1].date()}", "holdout_from": str(cut.date()),
                "walk_forward": W, "holdout": Ho, "regimes": regimes,
                "diff_ci99": {"up": [round(v, 5) for v in ci_up], "down": [round(v, 5) for v in ci_dn],
                              "path": [round(v, 4) for v in ci_pa]},
                "diff_mean": {"up": round(float(d_up.mean()), 5), "down": round(float(d_dn.mean()), 5),
                              "path": round(float(d_pa.mean()), 4)},
                "gates": g, "qualified": all(g.values())})
    rep["reason"] = "qualified" if rep["qualified"] else "failed: " + ", ".join(k.split()[0] for k, v in g.items() if not v)
    return rep


def evaluate_asset(h1: pd.DataFrame, kind: str) -> dict:
    return {name: evaluate(h1, kind, name) for name in PR.HORIZONS[kind]}
