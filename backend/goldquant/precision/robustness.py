"""Robustness Engine (V3 #7): does the accepted-trade edge survive realistic perturbations?

Run on OUT-OF-SAMPLE accepted trades of a candidate rule:
  1. costs x1.5 and x2            4. stop distance +-12.5 % (re-simulated)
  2. entry one bar later          5. month-by-month stability (share of months with positive EV)
  3. Gaussian noise on features (0.1 sd) with the SAME fitted models and threshold
Pass = EV stays > 0 in 1(x1.5), 2, 3 and 4, and >= 60 % of months (with >= 5 trades) are positive.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import model as M
from . import data as D
from .wf import COST, _proba, meta_features

MONTH_SHARE = 0.6


def _ev(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    return round(float(x.mean()), 4) if len(x) else None


def stress(oos: pd.DataFrame, rule: str, m15: pd.DataFrame, h1, h4, models: list | None = None, seed: int = 0) -> dict:
    acc = oos[oos[rule].astype(bool)]
    if len(acc) < 30:
        return {"status": "INSUFFICIENT", "accepted": len(acc), "passed": False,
                "reason_ar": "صفقات مقبولة خارج العينة أقل من 30"}
    out = {"accepted": len(acc), "base_ev": _ev(acc["pnl"])}
    out["cost_x1.5"] = _ev(acc["pnl"] - 0.5 * COST)
    out["cost_x2"] = _ev(acc["pnl"] - 1.0 * COST)
    table = D.feature_table(m15, h1, h4)
    late = D.build_signal_dataset(m15, h1, h4, entry_delay=2, table=table)
    out["entry_delay_1bar"] = _ev(late["pnl"].reindex(acc.index))
    for name, k in (("stop_minus_12pct", 1.75), ("stop_plus_12pct", 2.25)):
        alt = D.build_signal_dataset(m15, h1, h4, stop_atr=k, table=table)
        out[name] = _ev(alt["pnl"].reindex(acc.index))
    noise_ev = None
    if models and rule in ("acc_meta", "acc_meta_consensus"):
        rng = np.random.default_rng(seed)
        pn = []
        for fm in models:
            if fm["meta"] is None or fm["tau"] is None:
                continue
            te = fm["test"].copy()
            X = te[M.FEATURES].to_numpy(float)
            X = X + rng.normal(0, 0.1, X.shape) * X.std(axis=0, keepdims=True)
            p = _proba(fm["primary"], X)
            mp = fm["meta_cal"].transform(fm["meta"].predict_proba(meta_features(te, p, te.attrs.get("tp_r", 1.0)))[:, 1])
            pn.append(te["pnl"].to_numpy()[mp >= fm["tau"]])
        if pn:
            noise_ev = _ev(np.concatenate(pn))
    out["feature_noise_0.1sd"] = noise_ev
    month = acc.groupby(acc["decision_time"].dt.tz_localize(None).dt.to_period("M"))["pnl"].agg(["mean", "count"])
    month = month[month["count"] >= 5]
    out["months_evaluated"] = int(len(month))
    out["positive_month_share"] = round(float((month["mean"] > 0).mean()), 3) if len(month) else None
    checks = [out["cost_x1.5"], out["entry_delay_1bar"], out["stop_minus_12pct"], out["stop_plus_12pct"]]
    if noise_ev is not None:
        checks.append(noise_ev)
    ok = all(c is not None and c > 0 for c in checks) and (out["positive_month_share"] or 0) >= MONTH_SHARE
    out["passed"] = bool(ok)
    out["status"] = "OK"
    return out
