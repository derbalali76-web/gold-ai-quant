"""Speed-ups on the free server must not change a single published number."""
import numpy as np
from sklearn.metrics import roc_auc_score

from goldquant import levels as LV


def test_fast_auc_equals_sklearn_with_ties():
    rng = np.random.default_rng(5)
    for n in (5, 40, 700):
        for _ in range(50):
            y = rng.integers(0, 2, n)
            if len(np.unique(y)) < 2:
                continue
            s = np.round(rng.normal(size=n), 1)  # many ties
            assert abs(LV._auc(y, s) - roc_auc_score(y, s)) < 1e-12
            b = rng.integers(0, 4, n).astype(float)  # integer scores (the "tests only" baseline)
            assert abs(LV._auc(y.astype(bool), b) - roc_auc_score(y, b)) < 1e-12


def test_outcome3_attach_uses_usable_cell_and_lead_rule():
    from goldquant import brief as BR
    from goldquant.schemas import DailyBrief
    b = DailyBrief(date="2026-11-17", bias="SIDEWAYS", price=72.44)
    cell = [0.525, 0.236, 0.238, 2899, 0.504, 0.26, 0.236, 581, True]
    table = {"outcome3": {"version": "outcome3-0.1.0", "window_hours": 24, "cells": {"2.0|3.5": cell}}}
    BR.attach_outcome3(b, table, 72.44, 69.82, 76.77, 1.289)
    assert b.outcome3 and b.outcome3.likely == "DOWN" and abs(b.outcome3.p_down + b.outcome3.p_up + b.outcome3.p_none - 1) < 0.01
    b2 = DailyBrief(date="d", bias="SIDEWAYS", price=72.44)
    BR.attach_outcome3(b2, {"outcome3": {"cells": {"2.0|3.5": [0.40, 0.37, 0.23, 2899, 0.4, 0.37, 0.23, 581, True]}}},
                       72.44, 69.82, 76.77, 1.289)
    assert b2.outcome3 and b2.outcome3.likely is None  # lead < 5 points: no clear most-likely
    b3 = DailyBrief(date="d", bias="SIDEWAYS", price=72.44)
    BR.attach_outcome3(b3, {"outcome3": {"cells": {"2.0|3.5": cell[:8] + [False]}}}, 72.44, 69.82, 76.77, 1.289)
    assert b3.outcome3 is None  # not stable out of sample: nothing


def test_outcome3_table_adds_up_and_is_stable_by_construction():
    import pandas as pd
    from goldquant import brief as BR
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, 6000)))
    idx = pd.date_range("2025-01-01", periods=6000, freq="h", tz="UTC")
    h1 = pd.DataFrame({"high": c * 1.002, "low": c * 0.998, "close": c}, index=idx)
    t = BR.outcome_table(h1, 24)
    for v in t["cells"].values():
        assert abs(sum(v[:3]) - 1) < 0.01
