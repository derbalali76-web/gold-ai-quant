"""Multi-timeframe directional bias. Shared by the live engine and the backtester so both use the same rule.
It decides only the DIRECTION to evaluate; it is never used as a probability."""
from __future__ import annotations

import numpy as np

MIN_BIAS = 0.5
W_H4, W_H1, W_M30, W_M15, W_VR = 0.35, 0.25, 0.15, 0.15, 0.10


def bias_score(h4_slope, h1_slope, m30_dist, m15_ret16, vr):
    h4_slope, h1_slope, m30_dist, m15_ret16, vr = (np.asarray(x, dtype=float) for x in
                                                    (h4_slope, h1_slope, m30_dist, m15_ret16, vr))
    s4 = np.where(np.abs(h4_slope) > 0.1, np.sign(h4_slope), 0.0)
    s1 = np.where(np.abs(h1_slope) > 0.1, np.sign(h1_slope), 0.0)
    s30 = np.sign(np.nan_to_num(m30_dist))
    s15 = np.where(np.abs(m15_ret16) > 0.5, np.sign(m15_ret16), 0.0)
    b = W_H4 * s4 + W_H1 * s1 + W_M30 * s30 + W_M15 * s15
    return b + np.where(np.nan_to_num(vr) > 1.05, W_VR * np.sign(b), 0.0)


def direction(score):
    score = np.asarray(score, dtype=float)
    return np.where(np.abs(score) >= MIN_BIAS, np.sign(score), 0.0).astype(int)
