"""Dynamic Barrier Optimization (V3 #6).

A small, pre-declared grid of (stop in ATR, target in R) is evaluated. In every walk-forward fold the
configuration is CHOSEN on the calibration window (mean net pnl of the model-accepted trades, >= 30 trades)
and then EVALUATED on the following test window — so the reported result includes the cost of choosing.
The default (2.0 ATR, 1R) is evaluated identically for comparison. Objective = net expected value, not win rate.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import model as M
from . import data as D
from .wf import COST, MIN_EDGE_R, _logit, _proba, block_bootstrap_mean

GRID = [(s, r) for s in (1.5, 2.0, 2.5, 3.0) for r in (1.0, 1.5, 2.0)]
DEFAULT = (2.0, 1.0)


def _accept(m, X, rows, stop_atr, tp_r):
    p = _proba(m, X)
    risk = rows["atr"].to_numpy() * stop_atr
    return (p[:, 0] * tp_r - p[:, 1] - COST / risk) >= MIN_EDGE_R


def optimize(m15, h1, h4, n_folds: int = 4, dev_frac: float = 0.8, cal_frac: float = 0.12, test_span_frac: float = 0.45,
             horizon_min: int = 240) -> dict:
    table = D.feature_table(m15, h1, h4)
    sets = {cfg: D.build_signal_dataset(m15, h1, h4, horizon_min, cfg[0], cfg[1], table=table) for cfg in GRID}
    any_s = sets[DEFAULT]
    t_min, t_max = any_s["decision_time"].min(), any_s["decision_time"].max()
    span = t_max - t_min
    emb = pd.Timedelta(minutes=horizon_min)
    holdout = t_min + dev_frac * span
    t0s = [holdout - test_span_frac * span + (test_span_frac * span) * k / n_folds for k in range(n_folds + 1)]
    folds, chosen_pnl, default_pnl, chosen_days, default_days = [], [], [], [], []
    for f, (a, b) in enumerate(zip(t0s[:-1], t0s[1:])):
        c0, c1, tr_end = a - emb - cal_frac * span, a - emb, a - 2 * emb - cal_frac * span
        best, best_cfg, res = -np.inf, None, {}
        for cfg, S in sets.items():
            tr = S[S["known_at"] < tr_end]
            cal = S[(S["decision_time"] >= c0) & (S["decision_time"] < c1)]
            te = S[(S["decision_time"] >= a) & (S["decision_time"] < b) & (S["decision_time"] < holdout - emb)]
            if len(tr) < 1500 or tr["out"].nunique() < 3 or cal.empty or te.empty:
                continue
            m = _logit().fit(tr[M.FEATURES].to_numpy(), tr["out"].to_numpy())
            ac = _accept(m, cal[M.FEATURES].to_numpy(), cal, *cfg)
            at = _accept(m, te[M.FEATURES].to_numpy(), te, *cfg)
            res[cfg] = (te[at], ac.sum(), cal["pnl"].to_numpy()[ac].mean() if ac.sum() else np.nan)
            if ac.sum() >= 30 and res[cfg][2] > best:
                best, best_cfg = res[cfg][2], cfg
        if DEFAULT not in res:
            continue
        sel = best_cfg or DEFAULT
        folds.append({"fold": f, "chosen": list(sel), "chosen_on_cal_ev": None if best_cfg is None else round(float(best), 4),
                      "test_trades_chosen": len(res[sel][0]), "test_ev_chosen": _m(res[sel][0]),
                      "test_trades_default": len(res[DEFAULT][0]), "test_ev_default": _m(res[DEFAULT][0])})
        chosen_pnl.append(res[sel][0]["pnl"].to_numpy()); chosen_days.append(res[sel][0]["decision_time"].dt.floor("D").to_numpy())
        default_pnl.append(res[DEFAULT][0]["pnl"].to_numpy()); default_days.append(res[DEFAULT][0]["decision_time"].dt.floor("D").to_numpy())
    if not folds:
        return {"status": "INSUFFICIENT"}
    cp, dp = np.concatenate(chosen_pnl), np.concatenate(default_pnl)
    return {"status": "OK", "grid": [list(g) for g in GRID], "folds": folds,
            "dynamic": {"trades": len(cp), "ev": _mv(cp), "ev_ci95": block_bootstrap_mean(cp, np.concatenate(chosen_days))},
            "default": {"trades": len(dp), "ev": _mv(dp), "ev_ci95": block_bootstrap_mean(dp, np.concatenate(default_days))},
            "note_ar": "الاختيار يتم في نافذة المعايرة فقط ثم يُقيّم في نافذة اختبار لاحقة"}


def _m(df):
    return round(float(df["pnl"].mean()), 4) if len(df) else None


def _mv(x):
    return round(float(np.mean(x)), 4) if len(x) else None
