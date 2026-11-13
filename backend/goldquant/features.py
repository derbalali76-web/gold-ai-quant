"""As-of feature computations. Every function uses only rows up to and including the current row."""
from __future__ import annotations

import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def log_returns(df: pd.DataFrame) -> pd.Series:
    return np.log(df["close"]).diff()


def efficiency_ratio(close: pd.Series, n: int = 20) -> pd.Series:
    """Kaufman efficiency ratio: |net move| / path length. 1 = straight trend, ~0 = noise."""
    net = (close - close.shift(n)).abs()
    path = close.diff().abs().rolling(n).sum()
    return (net / path.replace(0, np.nan)).clip(0, 1)


def variance_ratio(close: pd.Series, q: int = 4, window: int = 96) -> pd.Series:
    """Lo-MacKinlay variance ratio over a rolling window. >1 trending/persistent, <1 mean-reverting."""
    r1 = np.log(close).diff()
    rq = np.log(close).diff(q)
    v1 = r1.rolling(window).var()
    vq = rq.rolling(window).var()
    return vq / (q * v1.replace(0, np.nan))


def robust_z(x: pd.Series, window: int = 200) -> pd.Series:
    med = x.rolling(window, min_periods=window // 2).median()
    mad = (x - med).abs().rolling(window, min_periods=window // 2).median()
    return (x - med) / (1.4826 * mad.replace(0, np.nan))


def realized_vol(df: pd.DataFrame, n: int) -> pd.Series:
    return log_returns(df).rolling(n).std()


def cusum_bars_since_break(close: pd.Series, h_mult: float = 5.0, vol_window: int = 96) -> pd.Series:
    """Two-sided CUSUM change-point detector on standardized returns. Returns bars since last alarm."""
    r = np.log(close).diff().fillna(0.0).to_numpy()
    sd = pd.Series(r).rolling(vol_window, min_periods=20).std().bfill().to_numpy()
    z = np.divide(r, sd, out=np.zeros_like(r), where=sd > 0)
    s_pos = s_neg = 0.0
    k = 0.5
    since = np.zeros(len(r))
    last = -10**9
    for i, zi in enumerate(z):
        s_pos = max(0.0, s_pos + zi - k)
        s_neg = min(0.0, s_neg + zi + k)
        if s_pos > h_mult or s_neg < -h_mult:
            last = i
            s_pos = s_neg = 0.0
        since[i] = i - last if last >= 0 else np.nan
    return pd.Series(since, index=close.index)


def session_of(ts: pd.Timestamp) -> str:
    h = ts.hour
    if ts.dayofweek == 5 or (ts.dayofweek == 6 and h < 22) or (ts.dayofweek == 4 and h >= 21):
        return "CLOSED"
    if h == 21:
        return "DAILY_BREAK"
    if h >= 22 or h < 7:
        return "ASIA"
    if h < 12:
        return "LONDON"
    if h < 16:
        return "LONDON_NY_OVERLAP"
    return "NEW_YORK"


SESSION_CODES = {"ASIA": 0, "LONDON": 1, "LONDON_NY_OVERLAP": 2, "NEW_YORK": 3, "DAILY_BREAK": 4, "CLOSED": 5}


def frame_features(df: pd.DataFrame) -> pd.DataFrame:
    """Per-timeframe feature table aligned to bar index (bar open time). Values valid at bar CLOSE."""
    out = pd.DataFrame(index=df.index)
    a = atr(df)
    e20, e50 = ema(df["close"], 20), ema(df["close"], 50)
    out["atr"] = a
    out["ema20"] = e20
    out["ema50"] = e50
    out["dist_ema20_atr"] = (df["close"] - e20) / a
    out["slope_ema50_atr"] = (e50 - e50.shift(5)) / a
    out["er20"] = efficiency_ratio(df["close"], 20)
    out["vr4"] = variance_ratio(df["close"], 4, 96)
    rv_s, rv_l = realized_vol(df, 16), realized_vol(df, 96)
    out["vol_ratio"] = rv_s / rv_l
    out["rv16"] = rv_s
    out["ret_z"] = robust_z(log_returns(df), 200)
    out["range_z"] = robust_z((df["high"] - df["low"]) / df["close"], 200)
    out["ret_4"] = np.log(df["close"]).diff(4) / (a / df["close"])
    out["ret_16"] = np.log(df["close"]).diff(16) / (a / df["close"])
    out["swing_high_12"] = df["high"].rolling(12).max()
    out["swing_low_12"] = df["low"].rolling(12).min()
    out["since_break"] = cusum_bars_since_break(df["close"])
    if "tick_volume" in df:
        out["tickvol_z"] = robust_z(np.log1p(df["tick_volume"]), 200)
    return out
