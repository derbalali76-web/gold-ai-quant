"""Micro-Edge Discovery (V2 #17) with multiple-testing control.

Cells = (feature quintile x session x direction). Each cell's P(target first) is tested against the
development base rate (two-sided binomial). Benjamini-Hochberg controls the false-discovery rate across ALL
cells. Survivors must then hold in a later, untouched confirmation period (one-sided, same sign).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .. import model as M

CANDIDATES = ["er20", "vr4", "vol_ratio", "dist_ema20_atr", "slope_ema50_atr", "ret_16", "h4_slope_ema50_atr", "range_z"]


def benjamini_hochberg(p: np.ndarray, q: float = 0.05) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    n = len(p)
    if n == 0:
        return np.array([], dtype=bool)
    order = np.argsort(p)
    thresh = q * (np.arange(1, n + 1) / n)
    passed = p[order] <= thresh
    k = np.max(np.where(passed)[0]) + 1 if passed.any() else 0
    out = np.zeros(n, dtype=bool)
    out[order[:k]] = True
    return out


def discover(ds: pd.DataFrame, horizon: int = 240, dev_frac: float = 0.6, min_n: int = 100, q: float = 0.05) -> dict:
    d = ds.dropna(subset=[f"out_{horizon}"]).copy()
    d["y"] = (d[f"out_{horizon}"] == 1).astype(int)
    times = d["decision_time"].sort_values().unique()
    cut = times[int(len(times) * dev_frac)]
    gap = pd.Timedelta(minutes=horizon)
    dev = d[d[f"known_{horizon}"] < cut]
    conf = d[d["decision_time"] >= cut + gap]
    base = dev["y"].mean()
    cells = []
    for f in CANDIDATES:
        edges = np.unique(np.quantile(dev[f], [0, .2, .4, .6, .8, 1]))
        if len(edges) < 3:
            continue
        edges[0], edges[-1] = -np.inf, np.inf
        for frame, name in ((dev, "dev"), (conf, "conf")):
            frame[f"_b_{f}"] = pd.cut(frame[f], edges, labels=False)
        for (b, s, di), g in dev.groupby([f"_b_{f}", "session", "dir"]):
            if len(g) < min_n:
                continue
            k = int(g["y"].sum())
            p = stats.binomtest(k, len(g), base).pvalue
            cells.append({"feature": f, "bin": int(b), "session": s, "dir": int(di), "n": len(g),
                          "rate": k / len(g), "p": p})
    if not cells:
        return {"tested": 0, "dev_significant": 0, "confirmed": [], "base_rate": base}
    pv = np.array([c["p"] for c in cells])
    keep = benjamini_hochberg(pv, q)
    confirmed = []
    for c, ok in zip(cells, keep):
        if not ok:
            continue
        g = conf[(conf[f"_b_{c['feature']}"] == c["bin"]) & (conf["session"] == c["session"]) & (conf["dir"] == c["dir"])]
        if len(g) < 30:
            continue
        k = int(g["y"].sum())
        alt = "greater" if c["rate"] > base else "less"
        p2 = stats.binomtest(k, len(g), base, alternative=alt).pvalue
        if p2 < 0.05:
            confirmed.append({**c, "conf_n": len(g), "conf_rate": round(k / len(g), 4), "conf_p": round(p2, 5)})
    return {"tested": len(cells), "dev_significant": int(keep.sum()), "confirmed": confirmed,
            "base_rate": round(float(base), 4), "fdr_q": q,
            "note_ar": "الأنماط المؤكدة فقط (نجت من تصحيح الاختبارات المتعددة ثم صمدت في فترة لاحقة لم تُستخدم)"}
