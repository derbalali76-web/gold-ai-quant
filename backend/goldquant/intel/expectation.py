"""Expectation Gap (V2 #2), Priced-In (V2 #15) and Missing Reaction (V2 #13).

All three need scheduled events with consensus AND actual values and their exact publication times.
Without them the functions return None and the engines stay disabled — no values are invented.
Gold returns around an event use only bars closed by the evaluation time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_HISTORY = 8


def standardized_surprise(actual: float, consensus: float, past_surprises: list[float]) -> float | None:
    if actual is None or consensus is None:
        return None
    raw = actual - consensus
    hist = [s for s in past_surprises if s is not None]
    if len(hist) < MIN_HISTORY:
        return None  # cannot scale without history: do not pretend
    sd = float(np.std(hist, ddof=1))
    return raw / sd if sd > 0 else None


def _ret(m15: pd.DataFrame, t0: pd.Timestamp, t1: pd.Timestamp) -> float | None:
    close_t = m15.index + pd.Timedelta(minutes=15)
    a = m15["close"][close_t <= t0]
    b = m15["close"][close_t <= t1]
    if a.empty or b.empty:
        return None
    return float(np.log(b.iloc[-1] / a.iloc[-1]))


def reaction_beta(events: list[dict], m15: pd.DataFrame, window_min: int = 30) -> dict | None:
    """Historical gold reaction per 1 sd of surprise for one event type. events: {time_utc, surprise_z}."""
    xs, ys = [], []
    for e in events:
        if e.get("surprise_z") is None:
            continue
        t = pd.Timestamp(e["time_utc"])
        r = _ret(m15, t - pd.Timedelta(minutes=5), t + pd.Timedelta(minutes=window_min))
        if r is not None:
            xs.append(e["surprise_z"])
            ys.append(r)
    if len(xs) < MIN_HISTORY:
        return None
    x, y = np.array(xs), np.array(ys)
    beta = float(np.sum(x * y) / np.sum(x * x)) if np.sum(x * x) > 0 else 0.0
    resid_sd = float(np.std(y - beta * x, ddof=1))
    return {"beta": beta, "resid_sd": resid_sd, "n": len(xs)}


def priced_in(m15: pd.DataFrame, event_time, surprise_z: float, beta: dict, pre_hours: int = 24) -> dict | None:
    """Share of the expected reaction already realised in the drift BEFORE the release."""
    if beta is None or surprise_z is None:
        return None
    t = pd.Timestamp(event_time)
    pre = _ret(m15, t - pd.Timedelta(hours=pre_hours), t - pd.Timedelta(minutes=5))
    expected = beta["beta"] * surprise_z
    if pre is None or expected == 0:
        return None
    share = pre / expected
    return {"pre_drift": pre, "expected_reaction": expected, "share_priced_in": round(float(share), 3),
            "label_ar": "سُعّر مسبقاً إلى حد كبير" if share >= 0.7 else "لم يُسعّر بالكامل"}


def missing_reaction(m15: pd.DataFrame, event_time, surprise_z: float, beta: dict, as_of, window_min: int = 30) -> dict | None:
    """Flags a reaction much smaller than history implies (|actual - expected| > 2 resid sd and |actual| tiny)."""
    if beta is None or surprise_z is None:
        return None
    t = pd.Timestamp(event_time)
    if pd.Timestamp(as_of) < t + pd.Timedelta(minutes=window_min):
        return None  # not enough time elapsed yet
    actual = _ret(m15, t - pd.Timedelta(minutes=5), t + pd.Timedelta(minutes=window_min))
    if actual is None:
        return None
    expected = beta["beta"] * surprise_z
    gap = (actual - expected) / beta["resid_sd"] if beta["resid_sd"] > 0 else 0.0
    missing = abs(expected) > 2 * beta["resid_sd"] and abs(actual) < 0.25 * abs(expected)
    return {"actual": actual, "expected": expected, "gap_sd": round(float(gap), 2), "missing_reaction": bool(missing)}
