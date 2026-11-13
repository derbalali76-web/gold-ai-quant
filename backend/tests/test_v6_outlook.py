"""V6: multi-horizon outlook (WEEK / MONTH), daily trend filter, forward log, wider news embargo."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from goldquant import outlook as OL
from goldquant import outlook_log as OLOG
from goldquant.anti_trade import TradeCandidate, evaluate
from goldquant.schemas import Action, HorizonOutlook


def _daily(n=3000, seed=1, drift=0.0, vol=0.009):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-02", periods=n, tz="UTC")
    r = drift + rng.normal(0, vol, n)
    c = 1500 * np.exp(np.cumsum(r))
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.002, "low": np.minimum(o, c) * 0.998,
                         "close": c, "tick_volume": 0.0}, index=idx)


def _as_of(d):
    return (d.index[-1] + pd.Timedelta(days=1)).to_pydatetime()


def test_no_lookahead_future_bars_do_not_change_outlook():
    d = _daily()
    cut = d.index[2500] + pd.Timedelta(days=1)
    a = OL.compute(d, cut.to_pydatetime())
    tampered = d.copy()
    tampered.loc[tampered.index > d.index[2500], "close"] *= 1.5  # wildly different future
    tampered["high"] = tampered[["open", "close", "high"]].max(axis=1)
    b = OL.compute(tampered, cut.to_pydatetime())
    for x, y in zip(a, b):
        assert (x.action, x.tilt, x.stats.n, x.stats.hit_rate) == (y.action, y.tilt, y.stats.n, y.stats.hit_rate)


def test_random_walk_rules_are_not_validated():
    views = OL.compute(_daily(seed=7), _as_of(_daily(seed=7)))
    assert all(not v.validated and v.action in ("WAIT", "UNAVAILABLE") for v in views)


def test_short_history_is_unavailable():
    d = _daily(n=200)
    views = OL.compute(d, _as_of(d))
    assert [v.action for v in views] == ["UNAVAILABLE", "UNAVAILABLE"]


def test_non_overlapping_samples_and_validation_on_persistent_trend():
    # strongly persistent regimes: the monthly momentum rule should beat the base rate
    rng = np.random.default_rng(3)
    n = 4000
    state = np.repeat(rng.choice([-1, 1], size=n // 250 + 1), 250)[:n]
    r = state * 0.002 + rng.normal(0, 0.006, n)
    idx = pd.bdate_range("2008-01-01", periods=n, tz="UTC")
    c = 1000 * np.exp(np.cumsum(r))
    d = pd.DataFrame({"open": c, "high": c * 1.003, "low": c * 0.997, "close": c, "tick_volume": 0.0}, index=idx)
    f = OL.daily_features(d)
    sig = OL.rule_signals(f, "MONTH")
    st = OL.evaluate_rule(f, sig, "MONTH")
    assert st.n >= OL.MIN_SIGNALS["MONTH"] and st.validated, st
    assert st.hit_rate > st.base_rate
    # find a date where the rule fires and check the produced card
    fire = np.flatnonzero(sig.to_numpy() != 0)
    t = d.index[fire[-1]] + pd.Timedelta(days=1)
    v = [x for x in OL.compute(d[d.index < t], t.to_pydatetime()) if x.horizon == "MONTH"][0]
    if v.validated and v.tilt:
        assert v.action in ("BUY", "SELL")
        card = HorizonOutlook(horizon="MONTH", label_ar="شهر", action=Action(v.action), tilt=v.tilt, stance_ar=v.stance_ar,
                              reason_ar=v.reason_ar, validated=True, hit_rate=v.stats.hit_rate, samples=v.stats.n,
                              entry_price=v.entry_price, stop_loss=v.stop_loss, target=v.target)
        assert card.action == Action(v.action)


def test_schema_refuses_unvalidated_long_trade_and_unvalidated_hit_rate():
    with pytest.raises(ValueError):
        HorizonOutlook(horizon="WEEK", label_ar="أسبوع", action=Action.BUY, stance_ar="شراء", reason_ar="",
                       validated=False, entry_price=100, stop_loss=95, target=110)
    with pytest.raises(ValueError):
        HorizonOutlook(horizon="WEEK", label_ar="أسبوع", action=Action.WAIT, stance_ar="انتظار", reason_ar="",
                       validated=False, hit_rate=0.6, samples=100)
    with pytest.raises(ValueError):  # inverted levels
        HorizonOutlook(horizon="MONTH", label_ar="شهر", action=Action.SELL, stance_ar="بيع", reason_ar="",
                       validated=True, entry_price=100, stop_loss=95, target=110)


def test_daily_trend():
    up = _daily(n=600, drift=0.002, vol=0.004)
    dn = _daily(n=600, drift=-0.002, vol=0.004)
    assert OL.daily_trend(up, _as_of(up)) == 1
    assert OL.daily_trend(dn, _as_of(dn)) == -1
    assert OL.daily_trend(up.head(100), _as_of(up.head(100))) == 0


def test_engine_attaches_three_horizons(demo):
    from goldquant.engine import DecisionEngine
    from goldquant.schemas import Mode
    from goldquant.store import Store
    d = DecisionEngine(Store()).decide(demo, Mode.DEMO, demo.default_as_of())
    assert [o.horizon for o in d.outlooks] == ["HOURS", "WEEK", "MONTH"]
    assert all(o.hit_rate is None for o in d.outlooks)  # DEMO: never numbers


def test_forward_log_is_idempotent_and_resolves(tmp_path):
    d = _daily(n=700, drift=0.002, vol=0.004)
    log = tmp_path / "outlook_log.jsonl"
    cut = d.index[650] + pd.Timedelta(days=1)
    first = OLOG.append_today(d, cut.to_pydatetime(), log)
    again = OLOG.append_today(d, cut.to_pydatetime(), log)
    assert len(first) == 2 and again == []
    track = OLOG.resolve(OLOG.read_log(log), d)
    month = track["horizons"]["MONTH"]
    if first[1]["tilt"]:
        assert month["resolved"] == 1 and month["pending"] == 0


def test_calendar_wider_embargo_and_upcoming():
    from goldquant.sources.calendar import Calendar, CalendarEvent
    t = datetime(2026, 11, 13, 13, 30, tzinfo=timezone.utc)
    cal = Calendar([CalendarEvent(t, "US CPI", 3, "bls.gov")], t - timedelta(days=1))
    assert cal.embargo(t - timedelta(minutes=50), before_min=60, after_min=45)
    assert not cal.embargo(t - timedelta(minutes=50))  # old ±30 window would miss it
    assert [e.name for e in cal.upcoming(t - timedelta(hours=30))] == ["US CPI"]


def test_probability_margin_gate():
    c = TradeCandidate(direction=1, mode_live=False, data_fresh=True, vol_regime="STRONG_TREND", path_qualified=True,
                       p_tp=0.41, p_sl=0.39, expected_net_return=1.0, news_calendar_connected=True,
                       uncertainty_level="LOW")
    assert any("ضئيل" in r for r in evaluate(c))
