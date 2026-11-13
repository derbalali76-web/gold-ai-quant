"""Out-of-sample value of the extended feature sets (session clock, cross-asset context).

Same purged walk-forward as production validation; the delta in multiclass Brier versus the production feature
set is reported per horizon. A feature set is 'promotable' only if it improves Brier by more than the minimum
on LIVE data — the result is advisory and production stays unchanged until promoted.
"""
from __future__ import annotations

import pandas as pd

from .. import model as M
from .. import path as P
from ..features_ext import cross_asset_features, cross_columns, time_features


def _extend(ds: pd.DataFrame, extra: pd.DataFrame, directional: list[str]) -> pd.DataFrame:
    e = extra.reindex(ds["decision_time"]).reset_index(drop=True)
    e.index = ds.index
    out = pd.concat([ds, e], axis=1)
    for c in directional:
        out[c] = out[c] * out["dir"]
    return out


def compare(m15, h1, h4, aux: dict | None = None, horizon: int = 240, dataset_label: str = "") -> dict:
    ds = P.build_path_dataset(m15, h1, h4)
    times = pd.DatetimeIndex(ds["decision_time"].unique())
    tf = time_features(times)
    variants = {"production": [], "plus_time": list(tf.columns)}
    extra = tf
    directional = []
    if aux:
        cf = cross_asset_features(times, m15, aux)
        extra = pd.concat([tf, cf], axis=1)
        directional = cross_columns(cf.attrs["assets"])
        variants["plus_time_cross"] = list(tf.columns) + directional
    dsx = _extend(ds, extra, directional).dropna(subset=list(extra.columns))
    original = list(M.FEATURES)
    out = {}
    try:
        for name, cols in variants.items():
            M.FEATURES[:] = original + cols
            r = P.walk_forward_horizon(dsx, horizon)
            out[name] = {"n_oos": r.n_oos, "brier": r.brier_model, "climatology": r.brier_climatology,
                         "max_reliability_gap": r.max_reliability_gap}
    finally:
        M.FEATURES[:] = original
    base = out["production"]["brier"]
    for k, v in out.items():
        v["delta_vs_production"] = round(v["brier"] - base, 5)
        v["promotable"] = bool(k != "production" and dataset_label.startswith("LIVE")
                               and v["delta_vs_production"] < -P.MIN_BRIER_IMPROVEMENT)
    return {"dataset": dataset_label, "horizon": horizon, "variants": out,
            "cross_asset_available": bool(aux), "note_ar": "قيمة سالبة = تحسّن. لا تدخل الإنتاج إلا بعد الترقية على بيانات حية."}
