"""Full V3 precision evaluation: calibration, meta-labeling, selective prediction, consensus, mixture of
experts, dynamic barriers, robustness and the promotion gate — one reproducible report."""
from __future__ import annotations

import dataclasses

import numpy as np

from .. import path as P
from . import barrier as BR
from . import data as D
from . import promotion as PR
from . import robustness as RB
from . import wf as W

CANDIDATES = ("acc_calibrated_ev", "acc_moe_ev", "acc_meta", "acc_meta_consensus")


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, float) and np.isnan(o):
        return None
    return o


def full_report(m15, h1, h4, dataset_label: str, with_barrier: bool = True) -> dict:
    S = D.build_signal_dataset(m15, h1, h4)
    ds = P.build_path_dataset(m15, h1, h4)
    r = W.run(S, ds, keep_models=True)
    if r["status"] != "OK":
        return {"dataset": dataset_label, **r}
    oos = r["oos"]
    rules = W.rule_report(oos)
    robust = {c: RB.stress(oos, c, m15, h1, h4, r["models"]) for c in CANDIDATES}
    promos = [PR.evaluate(rules, c, robust[c]) for c in CANDIDATES]
    out = {
        "dataset": dataset_label,
        "objective_ar": "الهدف: عائد متوقع موجب بعد السبريد والانزلاق، لا تعظيم نسبة النجاح وحدها",
        "validation_ar": ("walk-forward متداخل: تدريب ← حظر ← نافذة معايرة/اختيار عتبات ← حظر ← اختبار. "
                          "آخر 20% محجوزة ولم تُلمس"),
        "signals_total": int(len(S)), "oos_signals": int(len(oos)),
        "folds": [dataclasses.asdict(f) for f in r["folds"]],
        "rules": rules,
        "precision_coverage_frontier": W.frontier(oos),
        "calibration": W.calibration_report(oos),
        "consensus": W.consensus_report(oos),
        "robustness": robust,
        "promotion": promos,
        "note_95_ar": ("نسبة 95% لا تُعتبر مثبتة إلا إذا كان الحد الأدنى لفاصل الثقة 95% لنسبة النجاح ≥ 0.95 "
                       "على عينة خارج العينة كافية (precision_95_proven)."),
    }
    if with_barrier:
        out["dynamic_barrier"] = BR.optimize(m15, h1, h4)
    return _clean(out)
