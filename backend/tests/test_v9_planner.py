"""Trade-plan engine: no look-ahead, conservative simulation, honest qualification."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from goldquant import planner as PL


def _walk(n=1600, seed=3, drift=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=n, freq="B", tz="UTC")
    c = 1500 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.006, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.006, n))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c}, index=idx)


def test_features_at_t_ignore_the_future():
    d = _walk(600)
    f1 = PL.features(d).iloc[400]
    d2 = d.copy()
    d2.iloc[401:, :] *= 1.5  # rewrite the future
    f2 = PL.features(d2).iloc[400]
    pd.testing.assert_series_equal(f1, f2)


def test_same_bar_target_and_stop_counts_as_stop():
    o = np.array([100, 100, 100.0]); c = np.array([100, 100, 100.0])
    h = np.array([100, 110, 100.0]); l = np.array([100, 90, 100.0])
    atr = np.array([5.0, 5.0, 5.0])
    out, ret, held = PL.simulate(o, h, l, c, atr, 0, PL.Candidate(1, "MARKET", 1.0, 1.0), 1, 1)
    assert out == -1 and ret < 0 and held == 1


def test_unfilled_limit_is_not_a_trade():
    o = c = np.full(6, 100.0); h = np.full(6, 100.5); l = np.full(6, 99.9)  # never pulls back 0.5 ATR
    atr = np.full(6, 2.0)
    out, ret, held = PL.simulate(o, h, l, c, atr, 0, PL.Candidate(1, "LIMIT", 1.0, 1.0), 3, 2)
    assert np.isnan(out) and ret == 0.0


def test_purge_keeps_training_outcomes_before_the_test_block():
    tr = PL._purged_train(1000, 5, 2)
    assert tr.max() + 5 + 2 < 1000 - 5  # outcome known before the block, plus an embargo


def test_random_walk_never_qualifies():
    r = PL.walk_forward(_walk(1600), "WEEK")
    assert not r.qualified
    assert r.direction_accuracy is None or abs(r.direction_accuracy - 0.5) < 0.1


def test_planner_plan_only_live_and_qualified():
    from goldquant.plans import planner_plan
    from goldquant.schemas import Action, Decision, DataFreshness, HorizonOutlook, Mode, SpotOrProxy

    class Fake:
        qualified = True
        report = {"probabilities_calibrated": False}

        def best_plan(self, d):
            return {"direction": 1, "entry_kind": "MARKET", "entry": 100.0, "target": 110.0, "stop": 95.0,
                    "ev_pct": 0.5, "p_target": 0.4, "p_stop": 0.3, "p_timeout": 0.3, "p_fill": 1.0,
                    "median_days_to_target": 8.0, "horizon_days": 21, "fill_days": 0}
    now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    daily = _walk(300)
    daily.index = pd.date_range(end="2026-11-09", periods=300, freq="D", tz="UTC")
    base = dict(decision_id="x", action=Action.WAIT, spot_or_proxy=SpotOrProxy.SPOT, provider="p", analyzed_at_utc=now,
                model_version="m", data_freshness=DataFreshness(max_allowed_seconds=60, is_fresh=True),
                data_quality="GOOD", snapshot_hash="h")
    o = HorizonOutlook(horizon="MONTH", label_ar="شهر", action=Action.WAIT, stance_ar="x", reason_ar="y")
    live = Decision(mode=Mode.LIVE, **base)
    p = planner_plan(live, o, Fake(), daily)
    assert p.recommendation and p.setup.value == "BUY_NOW" and p.p_target_first is None  # uncalibrated: hidden
    o2 = HorizonOutlook(horizon="MONTH", label_ar="شهر", action=Action.WAIT, stance_ar="x", reason_ar="y")
    demo = Decision(mode=Mode.DEMO, **{**base, "spot_or_proxy": SpotOrProxy.SYNTHETIC})
    assert planner_plan(demo, o2, Fake(), daily) is None
    Fake.qualified = False
    assert planner_plan(live, o2, Fake(), daily) is None
