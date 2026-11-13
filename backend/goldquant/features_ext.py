"""Extended features (research tier): session clock, scheduled flows and intraday cross-asset context.

They are NOT in the production feature set. /research/feature-upgrade measures their out-of-sample value
and they can only enter production through the promotion gate.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

LONDON, NEW_YORK = ZoneInfo("Europe/London"), ZoneInfo("America/New_York")
TIME_FEATURES = ["min_since_london_open", "min_since_ny_open", "near_london_pm_fix", "dow_sin", "dow_cos",
                 "month_end"]
CROSS_ASSETS = {"EURUSD": -1.0, "USDJPY": 1.0, "XAGUSD": 1.0}  # sign: + means "moves like a stronger dollar" for FX


def time_features(close_times: pd.DatetimeIndex) -> pd.DataFrame:
    """DST-aware session clock (London 08:00, New York 08:20 COMEX open, London PM fix 15:00 London)."""
    lt, nt = close_times.tz_convert(LONDON), close_times.tz_convert(NEW_YORK)
    lmin = lt.hour * 60 + lt.minute
    nmin = nt.hour * 60 + nt.minute
    out = pd.DataFrame(index=close_times)
    out["min_since_london_open"] = np.clip((lmin - 8 * 60) / 60.0, -8, 12)
    out["min_since_ny_open"] = np.clip((nmin - (8 * 60 + 20)) / 60.0, -8, 12)
    out["near_london_pm_fix"] = (np.abs(lmin - 15 * 60) <= 30).astype(float)
    dow = close_times.dayofweek.to_numpy()
    out["dow_sin"], out["dow_cos"] = np.sin(2 * np.pi * dow / 5), np.cos(2 * np.pi * dow / 5)
    out["month_end"] = (close_times.is_month_end | (close_times + pd.Timedelta(days=1)).is_month_end).astype(float)
    return out


def cross_asset_features(close_times: pd.DatetimeIndex, gold_m15: pd.DataFrame, aux: dict[str, pd.DataFrame],
                         window: int = 96) -> pd.DataFrame:
    """As-of (bar CLOSE) returns of related markets and gold's residual vs. its rolling relationship."""
    out = pd.DataFrame(index=close_times)
    g = gold_m15["close"].copy()
    g.index = g.index + pd.Timedelta(minutes=15)
    gr = np.log(g).diff()
    cols = []
    for sym, df in aux.items():
        c = df["close"].copy()
        c.index = c.index + pd.Timedelta(minutes=15)
        r = np.log(c).diff()
        r = r.reindex(gr.index, method="ffill", limit=1)
        out[f"{sym}_ret4"] = (r.rolling(4).sum()).reindex(close_times).to_numpy()
        out[f"{sym}_ret16"] = (r.rolling(16).sum()).reindex(close_times).to_numpy()
        cov = gr.rolling(window).cov(r)
        beta = cov / r.rolling(window).var()
        resid = (gr - beta.shift(1) * r).rolling(16).sum()
        sd = (gr - beta.shift(1) * r).rolling(window).std() * 4
        out[f"{sym}_resid_z"] = (resid / sd).reindex(close_times).to_numpy()
        cols.append(sym)
    out.attrs["assets"] = cols
    return out


def cross_columns(assets) -> list[str]:
    return [f"{a}_{k}" for a in assets for k in ("ret4", "ret16", "resid_z")]
