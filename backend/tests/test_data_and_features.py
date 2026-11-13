import numpy as np
import pandas as pd
import pytest

from goldquant.features import atr, efficiency_ratio, frame_features, robust_z, session_of
from goldquant.providers.base import Bars, closed_bars
from goldquant.providers.demo import DemoProvider, generate_m1


def test_demo_is_deterministic():
    a = generate_m1.__wrapped__(seed=7, days=10)
    b = generate_m1.__wrapped__(seed=7, days=10)
    c = generate_m1.__wrapped__(seed=8, days=10)
    pd.testing.assert_frame_equal(a, b)
    assert not a["close"].equals(c["close"])


def test_ohlc_invariants_and_utc(demo_bars):
    for tf, df in demo_bars.items():
        Bars(tf, df, "demo", pd.Timestamp.now(tz="UTC")).validate()


def test_validate_rejects_corrupt_bars(demo_bars):
    df = demo_bars["H1"].tail(50).copy()
    df.iloc[10, df.columns.get_loc("high")] = df.iloc[10]["low"] - 1
    with pytest.raises(ValueError):
        Bars("H1", df, "x", pd.Timestamp.now(tz="UTC")).validate()


def test_no_weekend_bars(demo_bars):
    idx = demo_bars["M15"].index
    assert not ((idx.dayofweek == 5)).any()


def test_provider_returns_only_closed_bars(demo):
    as_of = pd.Timestamp("2025-12-30 13:37", tz="UTC").to_pydatetime()
    for tf, minutes in (("M15", 15), ("H1", 60), ("H4", 240)):
        df = demo.bars(tf, as_of, 100).df
        assert (df.index + pd.Timedelta(minutes=minutes) <= as_of).all()
    q = demo.quote(as_of)
    assert q.observed_at <= as_of


def test_closed_bars_excludes_forming_bar():
    idx = pd.date_range("2026-01-05 10:00", periods=4, freq="60min", tz="UTC")
    df = pd.DataFrame({"open": 1, "high": 1, "low": 1, "close": 1}, index=idx)
    out = closed_bars(df, "H1", pd.Timestamp("2026-01-05 12:30", tz="UTC"))
    assert list(out.index.hour) == [10, 11]


def test_atr_constant_range():
    idx = pd.date_range("2026-01-05", periods=40, freq="15min", tz="UTC")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}, index=idx)
    assert atr(df).iloc[-1] == pytest.approx(2.0)


def test_efficiency_ratio_extremes():
    up = pd.Series(np.arange(50, dtype=float))
    zig = pd.Series([0.0, 1.0] * 25)
    assert efficiency_ratio(up, 20).iloc[-1] == pytest.approx(1.0)
    assert efficiency_ratio(zig, 20).iloc[-1] < 0.1


def test_robust_z_flags_outlier():
    x = pd.Series(np.r_[np.random.default_rng(0).normal(0, 1, 300), 12.0])
    assert robust_z(x, 200).iloc[-1] > 6


@pytest.mark.parametrize("cut", [400, 777, 1500, 2600])
def test_features_have_no_lookahead(demo_bars, cut):
    """Property: features at row t must be identical whether or not future rows exist."""
    df = demo_bars["M15"].iloc[:3000]
    full = frame_features(df)
    trunc = frame_features(df.iloc[:cut])
    pd.testing.assert_series_equal(full.iloc[cut - 1], trunc.iloc[-1], check_names=False)


def test_sessions():
    assert session_of(pd.Timestamp("2026-01-10 12:00", tz="UTC")) == "CLOSED"  # Saturday
    assert session_of(pd.Timestamp("2026-01-05 13:00", tz="UTC")) == "LONDON_NY_OVERLAP"
    assert session_of(pd.Timestamp("2026-01-05 21:30", tz="UTC")) == "DAILY_BREAK"
    assert session_of(pd.Timestamp("2026-01-05 02:00", tz="UTC")) == "ASIA"
