"""Signal dataset for the V3 precision layer.

One row per decision time where the multi-timeframe rule proposes a direction (the PRIMARY model's
candidate trades). Each row carries as-of features, the barrier outcome, the time its outcome became known
and the realised NET pnl (USD/oz) of trading it with the same rules as the backtester:
entry at next bar open + half-spread + slippage, levels from the decision close, same-bar => stop,
timeout exit at the last close inside the wall-clock horizon minus half-spread.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import model as M
from ..bias import bias_score, direction as bias_direction
from ..features import frame_features
from ..risk import EST_SLIPPAGE, EST_SPREAD

VREG = ("STRONG_TREND", "RANGE", "HIGH_VOL", "EXCEPTIONAL")


def vectorized_vol_regime(f15: pd.DataFrame, lookback: int = 500) -> pd.Series:
    """Same thresholds as regime.classify + volatility_regime, computed as-of for every row."""
    rv = f15["rv16"]
    pct = rv.rolling(lookback, min_periods=51).apply(lambda w: float((w <= w[-1]).mean()), raw=True)
    er, vr, slope, z = f15["er20"], f15["vr4"], f15["slope_ema50_atr"], f15["ret_z"].fillna(0.0)
    trend = (er >= 0.30) & (vr >= 1.0) & (slope.abs() >= 0.15)
    out = np.where((pct >= 0.97) | (z.abs() > 6), "EXCEPTIONAL",
                   np.where(pct >= 0.80, "HIGH_VOL", np.where(trend, "STRONG_TREND", "RANGE")))
    return pd.Series(out, index=f15.index)


def _m30_dist(m15: pd.DataFrame) -> pd.Series:
    m30 = m15.resample("30min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    f = frame_features(m30)["dist_ema20_atr"]
    f.index = f.index + pd.Timedelta(minutes=30)
    return f


def realised(m15: pd.DataFrame, atr15: np.ndarray, d: np.ndarray, horizon_min: int, stop_atr: float, tp_r: float,
             entry_delay: int = 1):
    """Vectorised outcome / net pnl / known-time for per-row direction d (0 rows return NaN)."""
    hi, lo, op, cl = (m15[k].to_numpy() for k in ("high", "low", "open", "close"))
    n = len(cl)
    t = (m15.index.as_unit("ns").asi8 // 60_000_000_000).astype(np.int64)
    risk = stop_atr * atr15
    stop = cl - d * risk
    target = cl + d * tp_r * risk
    e = np.minimum(np.arange(n) + entry_delay, n - 1)
    half = EST_SPREAD / 2
    entry = op[e] + d * (half + EST_SLIPPAGE)
    end_t = t + 15 + horizon_min
    last_idx = np.searchsorted(t + 15, end_t, side="right") - 1
    ok = (d != 0) & ~np.isnan(risk) & (end_t <= t[-1] + 15) & (last_idx >= e)
    outcome = np.full(n, np.nan)
    exit_p = np.full(n, np.nan)
    known = np.full(n, np.nan)
    open_ = ok.copy()
    max_k = horizon_min // 15 + entry_delay
    for k in range(0, max_k + 1):
        j = np.minimum(e + k, n - 1)
        live = open_ & (j <= last_idx)
        sl = np.where(d > 0, lo[j] <= stop, hi[j] >= stop)
        tp = np.where(d > 0, hi[j] >= target, lo[j] <= target)
        s_now, t_now = live & sl, live & tp & ~sl
        outcome[s_now], exit_p[s_now] = -1, (stop - d * EST_SLIPPAGE)[s_now]
        outcome[t_now], exit_p[t_now] = 1, target[t_now]
        known[s_now | t_now] = (t[j] + 15)[s_now | t_now]
        open_ &= ~(s_now | t_now)
    rest = open_
    outcome[rest] = 0
    exit_p[rest] = (cl[last_idx] - d * half)[rest]
    known[rest] = (t[last_idx] + 15)[rest]
    pnl = np.where(ok, d * (exit_p - entry), np.nan)
    return outcome, pnl, known


def build_signal_dataset(m15: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame, horizon_min: int = 240,
                         stop_atr: float = 2.0, tp_r: float = 1.0, entry_delay: int = 1,
                         table: pd.DataFrame | None = None) -> pd.DataFrame:
    if table is None:
        table = feature_table(m15, h1, h4)
    score = bias_score(table["h4_slope_ema50_atr"], table["h1_slope_ema50_atr"], table["m30_dist"],
                       table["ret_16"], table["vr4"])
    d = bias_direction(score)
    out, pnl, known = realised(m15, table["atr"].to_numpy(), d.astype(float), horizon_min, stop_atr, tp_r, entry_delay)
    s = table.copy()
    s["bias_abs"] = np.abs(score)
    for c in M.DIRECTIONAL:
        s[c] = s[c] * d
    s["dir"] = d.astype(float)
    s["out"], s["pnl"] = out, pnl
    s["known_at"] = pd.to_datetime(known, unit="m", utc=True)
    s["decision_time"] = s.index
    s = s[(s["dir"] != 0) & ~s["session"].isin(["CLOSED", "DAILY_BREAK"])]
    s = s.dropna(subset=M.FEATURES + ["out", "pnl"])
    s.attrs.update(horizon_min=horizon_min, stop_atr=stop_atr, tp_r=tp_r, entry_delay=entry_delay)
    return s


def feature_table(m15, h1, h4) -> pd.DataFrame:
    """Expose the cached feature table so several barrier configs can reuse it."""
    table = M.build_feature_table(m15, h1, h4)
    table = pd.merge_asof(table, _m30_dist(m15).rename("m30_dist").to_frame(), left_index=True, right_index=True)
    f15 = frame_features(m15)
    vr = vectorized_vol_regime(f15)
    vr.index = vr.index + pd.Timedelta(minutes=15)
    table["vreg"] = vr.reindex(table.index).to_numpy()
    return table
