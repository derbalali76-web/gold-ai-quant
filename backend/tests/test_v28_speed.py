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
