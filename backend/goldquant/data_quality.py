"""Automatic data-quality checks, run before any decision and over the whole stored history.

Every check returns OK / WARN / FAIL with a short machine-readable value. A FAIL on the bars a decision would use
blocks that decision (UNAVAILABLE: never a trade on broken data); WARN is shown but does not block.

Checks (intraday OHLC bars, bar index = OPEN time, UTC):
  freshness    last closed bar vs. the expected one (market hours aware)
  coverage     share of expected trading-hour bars present (last 5 trading days / whole history)
  gaps         longest run of missing trading-hour bars
  outliers     bar returns far outside the recent distribution (robust z-score on log returns)
  flat         runs of identical closes during open hours (feeds that keep printing a stale price)
  weekend      bars inside the weekly close (Fri 21:00 -> Sun 22:00 UTC) — not market prices
  ohlc         high/low consistent with open/close, positive prices
  cross_source median / max relative difference vs. a second source on common bars
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

TF_MIN = {"M15": 15, "M30": 30, "H1": 60, "H4": 240, "1h": 60, "15m": 15}
OK, WARN, FAIL = "OK", "WARN", "FAIL"
RANK = {OK: 0, WARN: 1, FAIL: 2}


def _ny(t: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return t.tz_convert("America/New_York")


def _closed(t: pd.DatetimeIndex) -> np.ndarray:
    """Weekly close, DST-aware: Friday 17:00 -> Sunday 18:00 New York time."""
    n = _ny(t)
    dow, h = n.day_of_week, n.hour
    return np.asarray((dow == 5) | ((dow == 4) & (h >= 17)) | ((dow == 6) & (h < 18)))


def _daily_break(t: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(_ny(t).hour == 17)  # 17:00-18:00 New York


def expected_index(start: pd.Timestamp, end: pd.Timestamp, tf: str, market: str = "metal") -> pd.DatetimeIndex:
    """Bar open times in [start, end) during trading hours (metal: no weekly close / daily break; crypto: 24/7)."""
    idx = pd.date_range(start.floor(f"{TF_MIN[tf]}min"), end, freq=f"{TF_MIN[tf]}min", inclusive="left")
    if market == "crypto":
        return idx
    keep = ~_closed(idx) & ~_daily_break(idx)
    return idx[keep]


def _check(code: str, status: str, value=None) -> dict:
    return {"code": code, "status": status, "value": None if value is None else str(value)}


def check_bars(df: pd.DataFrame, tf: str, now: datetime, window_days: Optional[float] = 7.0,
               other: Optional[pd.DataFrame] = None, market: str = "metal") -> dict:
    """Quality report for one bar series. window_days=None checks the whole history."""
    now_ts = pd.Timestamp(now)
    checks = []
    if df is None or len(df) == 0:
        return {"status": FAIL, "checks": [_check("coverage", FAIL, "0%")], "bars": 0}
    df = df[~df.index.duplicated()].sort_index()
    step = pd.Timedelta(minutes=TF_MIN[tf])
    start = df.index[0] if window_days is None else max(df.index[0], now_ts - pd.Timedelta(days=window_days))
    w = df[df.index >= start]

    # freshness: the most recent expected bar that should be closed by now
    exp_recent = expected_index(now_ts - pd.Timedelta(days=4), now_ts - step, tf, market)
    if len(exp_recent):
        lag = (exp_recent[-1] - df.index[-1]) / step
        checks.append(_check("freshness", OK if lag <= 2 else WARN if lag <= 8 else FAIL, f"{max(lag, 0):.0f}"))

    # coverage + longest gap over the window
    exp = expected_index(start, min(now_ts, w.index[-1] + step) if len(w) else now_ts, tf, market)
    if len(exp):
        present = exp.isin(w.index)
        cov = float(present.mean())
        checks.append(_check("coverage", OK if cov >= 0.97 else WARN if cov >= 0.85 else FAIL, f"{cov:.1%}"))
        miss = ~present
        longest, run = 0, 0
        for m in miss:
            run = run + 1 if m else 0
            longest = max(longest, run)
        hours = longest * TF_MIN[tf] / 60
        checks.append(_check("gaps", OK if hours <= 2 else WARN if hours <= 12 else FAIL, f"{hours:.1f}h"))

    if len(w) >= 3:
        o, h, l, c = (w[k].astype(float) for k in ("open", "high", "low", "close"))
        bad = int(((h < np.maximum(o, c)) | (l > np.minimum(o, c)) | (l <= 0)).sum())
        checks.append(_check("ohlc", OK if bad == 0 else FAIL, bad))

        if market != "crypto":
            wk = int(_closed(w.index).sum())
            checks.append(_check("weekend", OK if wk == 0 else WARN, wk))

        r = np.log(c).diff()
        r = r[(r.index.to_series().diff() == step).to_numpy()].dropna()  # intra-session only (no gap-opening bars)
        if len(r) >= 50:
            med = r.rolling(200, min_periods=50).median()
            mad = (r - med).abs().rolling(200, min_periods=50).median() * 1.4826
            floor = float((r - r.median()).abs().median() * 1.4826) * 0.5  # quiet stretches must not inflate z
            z = ((r - med) / np.maximum(mad.fillna(floor), floor if floor > 0 else 1e-12)).abs()
            n15 = int((z > 15).sum())
            n25 = int((z > 25).sum())
            checks.append(_check("outliers", OK if n15 == 0 else FAIL if n25 > 0 and window_days is not None else WARN,
                                 n15))

        openh = np.ones(len(w), bool) if market == "crypto" else ~_closed(w.index) & ~_daily_break(w.index)
        same = (c.diff() == 0) & (h == l) & openh
        longest, run = 0, 0
        for s in same.to_numpy():
            run = run + 1 if s else 0
            longest = max(longest, run)
        checks.append(_check("flat", OK if longest < 4 else WARN if longest < 8 else FAIL, longest))

    if other is not None and len(other) and len(w):
        common = w.index.intersection(other.index)
        if len(common) >= 20:
            a = w.loc[common, "close"].astype(float)
            b = other.loc[common, "close"].astype(float)
            rel = ((a - b).abs() / b)
            med, mx = float(rel.median()), float(rel.max())
            st = OK if med <= 0.0015 and mx <= 0.01 else WARN if med <= 0.004 else FAIL
            checks.append(_check("cross_source", st, f"{med:.3%}/{mx:.2%}"))
        else:
            checks.append(_check("cross_source", WARN, "n/a"))

    status = max((c_["status"] for c_ in checks), key=RANK.get, default=OK)
    return {"status": status, "checks": checks, "bars": int(len(w)),
            "first": str(df.index[0]), "last": str(df.index[-1])}


def decision_gate(bars: dict, now: datetime, market_open: bool) -> dict:
    """Quick check of the bars a live decision uses (last 7 days of M15 / H1). Freshness / coverage are only judged
    while the market is open (a closed market is expected to have no new bars)."""
    rep = {}
    for tf in ("M15", "H1"):
        b = bars.get(tf)
        if b is None:
            continue
        r = check_bars(b, tf, now, 7.0)
        if not market_open:
            r["checks"] = [x for x in r["checks"] if x["code"] not in ("freshness", "coverage", "gaps")]
        for x in r["checks"]:  # holidays and short outages make holes; they are shown, they do not block
            if x["code"] in ("coverage", "gaps", "weekend") and x["status"] == FAIL:
                x["status"] = WARN
        r["status"] = max((x["status"] for x in r["checks"]), key=RANK.get, default=OK)
        rep[tf] = r
    status = max((r["status"] for r in rep.values()), key=RANK.get, default=WARN)
    checks = []
    for tf, r in rep.items():
        for x in r["checks"]:
            checks.append(dict(x, code=f"{x['code']}", tf=tf))
    # keep the worst result per check code (one line per check in the app)
    worst: dict[str, dict] = {}
    for x in checks:
        if x["code"] not in worst or RANK[x["status"]] > RANK[worst[x["code"]]["status"]]:
            worst[x["code"]] = x
    return {"status": status, "checks": list(worst.values())}
