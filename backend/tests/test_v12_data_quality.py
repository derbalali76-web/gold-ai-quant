"""Automatic data-quality checks and the decision gate."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from goldquant import data_quality as DQ


def bars(n=700, start="2026-11-02 00:00", seed=1):
    idx = DQ.expected_index(pd.Timestamp(start, tz="UTC"), pd.Timestamp(start, tz="UTC") + pd.Timedelta(days=14), "M15")[:n]
    rng = np.random.default_rng(seed)
    c = 2000 * np.exp(np.cumsum(rng.normal(0, 0.0008, len(idx))))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.3, "low": np.minimum(o, c) - 0.3, "close": c}, index=idx)


def status(rep, code):
    return next(x["status"] for x in rep["checks"] if x["code"] == code)


def test_clean_series_passes():
    b = bars()
    rep = DQ.check_bars(b, "M15", b.index[-1].to_pydatetime() + pd.Timedelta(minutes=15), 7.0)
    assert rep["status"] == "OK", rep


def test_flat_stale_feed_fails_the_gate():
    b = bars()
    b.iloc[-12:, :] = b["close"].iloc[-13]  # a feed repeating one price
    now = b.index[-1].to_pydatetime() + pd.Timedelta(minutes=15)
    g = DQ.decision_gate({"M15": b}, now, True)
    assert g["status"] == "FAIL" and status(g, "flat") == "FAIL"


def test_spike_is_an_outlier():
    b = bars()
    i = len(b) - 5
    b.iloc[i, b.columns.get_loc("close")] *= 1.08
    b.iloc[i, b.columns.get_loc("high")] = b.iloc[i]["close"] + 0.3
    rep = DQ.check_bars(b, "M15", b.index[-1].to_pydatetime() + pd.Timedelta(minutes=15), 7.0)
    assert status(rep, "outliers") == "FAIL"


def test_holes_warn_but_do_not_block():
    b = bars()
    b = b.drop(b.index[300:400])  # a 25-hour outage
    g = DQ.decision_gate({"M15": b}, b.index[-1].to_pydatetime() + pd.Timedelta(minutes=15), True)
    assert status(g, "gaps") == "WARN" and g["status"] != "FAIL"


def test_cross_source_disagreement():
    a = bars()
    other = a.copy()
    other["close"] *= 1.02
    rep = DQ.check_bars(a, "M15", a.index[-1].to_pydatetime() + pd.Timedelta(minutes=15), 7.0, other=other)
    assert status(rep, "cross_source") == "FAIL"


def test_engine_reports_health():
    from goldquant.engine import DecisionEngine
    from goldquant.providers.demo import DemoProvider
    from goldquant.schemas import Mode
    from goldquant.store import Store
    demo = DemoProvider()
    t = (demo.m1().index[-1] + pd.Timedelta(minutes=1)).to_pydatetime()
    d = DecisionEngine(Store()).decide(demo, Mode.DEMO, t)
    assert d.data_health is not None and d.data_health.status in ("OK", "WARN")
    assert {c.code for c in d.data_health.checks} >= {"ohlc", "flat", "outliers"}
