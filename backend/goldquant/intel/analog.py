"""Historical Analog Engine (V2 #7): nearest past situations on standardized as-of features.

Neighbours come only from samples whose outcome was KNOWN before as_of, and samples within `gap` of as_of
are excluded so overlapping windows cannot leak. Reports the outcome distribution of the neighbours with
its sample size and a similarity measure — descriptive evidence, not a calibrated probability.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import model as M

FEATS = [f for f in M.FEATURES if f != "dir"]


def analogs(ds: pd.DataFrame, query: pd.Series, direction: int, as_of, horizon: int = 240, k: int = 50,
            gap: pd.Timedelta = pd.Timedelta(days=2)) -> dict | None:
    ts = pd.Timestamp(as_of)
    pool = ds[(ds["dir"] == direction) & (ds[f"known_{horizon}"] <= ts) & (ds["decision_time"] <= ts - gap)]
    pool = pool.dropna(subset=FEATS + [f"out_{horizon}"])
    if len(pool) < 5 * k:
        return None
    X = pool[FEATS].to_numpy(dtype=float)
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    q = (query[FEATS].to_numpy(dtype=float) - mu) / sd
    d = np.sqrt((((X - mu) / sd - q) ** 2).sum(axis=1))
    idx = np.argsort(d)[:k]
    out = pool[f"out_{horizon}"].to_numpy()[idx]
    base = pool[f"out_{horizon}"].to_numpy()
    return {"k": k, "pool": len(pool), "median_distance": round(float(np.median(d[idx])), 3),
            "typical_distance": round(float(np.median(d)), 3),
            "neighbours": {"target_first": round(float(np.mean(out == 1)), 3), "stop_first": round(float(np.mean(out == -1)), 3),
                           "neither": round(float(np.mean(out == 0)), 3)},
            "all_history": {"target_first": round(float(np.mean(base == 1)), 3), "stop_first": round(float(np.mean(base == -1)), 3)},
            "dates": [str(t.date()) for t in pool["decision_time"].iloc[idx[:5]]]}
