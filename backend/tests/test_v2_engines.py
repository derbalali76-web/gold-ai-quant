import numpy as np
import pandas as pd
import pytest

from goldquant import anti_trade as AT
from goldquant import drift as DR
from goldquant import model as M
from goldquant import path as P
from goldquant.regime import Regime, volatility_regime


# ---------------- Probabilistic Path
def test_outcomes_three_classes_and_ordering():
    flat = [100, 100.2, 99.8, 100]
    rows = [[100, 100, 100, 100]] * 4
    def df(bar):
        r = rows + [bar] + [flat] * 20
        idx = pd.date_range("2026-01-05 08:00", periods=len(r), freq="15min", tz="UTC")
        return pd.DataFrame(r, columns=["open", "high", "low", "close"], index=idx)
    atr = np.full(25, 1.0)
    assert M.barrier_outcomes(df([100, 102.5, 99.5, 102]), atr, 1, 16)[0][3] == 1
    assert M.barrier_outcomes(df([100, 100.5, 97.5, 98]), atr, 1, 16)[0][3] == -1
    assert M.barrier_outcomes(df([100, 103, 97, 100]), atr, 1, 16)[0][3] == -1  # same bar => stop
    assert M.barrier_outcomes(df(flat), atr, 1, 16)[0][3] == 0
    # shorter horizon cannot see the move that happens on bar 4 if horizon is 0 bars ahead... 1 bar sees it
    assert M.barrier_outcomes(df([100, 102.5, 99.5, 102]), atr, 1, 1)[0][3] == 1
    assert M.barrier_outcomes(df([100, 102.5, 99.5, 102]), atr, 1, 1)[0][2] == 0


@pytest.fixture(scope="module")
def path_ds(demo_bars):
    return P.build_path_dataset(demo_bars["M15"], demo_bars["H1"], demo_bars["H4"])


def test_path_dataset_known_times(path_ds):
    for h in P.HORIZONS_MIN:
        d = path_ds.dropna(subset=[f"out_{h}"])
        lag = d[f"known_{h}"] - d["decision_time"]
        assert (lag > pd.Timedelta(0)).all() and (lag <= pd.Timedelta(minutes=h)).all()
        assert set(np.unique(d[f"out_{h}"])) <= {-1.0, 0.0, 1.0}


def test_longer_horizon_never_has_more_neither(path_ds):
    share = [(path_ds[f"out_{h}"] == 0).mean() for h in P.HORIZONS_MIN]
    assert share == sorted(share, reverse=True)


def test_path_walk_forward_is_honest(path_ds):
    for h in (60, 240):
        r = P.walk_forward_horizon(path_ds, h)
        assert r.n_oos > 1000 and 0 < r.brier_model < 2 and 0 < r.brier_climatology < 2
        assert r.qualified == (r.brier_model < r.brier_climatology - P.MIN_BRIER_IMPROVEMENT
                               and r.max_reliability_gap <= P.MAX_RELIABILITY_GAP)


def test_path_models_predict_valid_simplex(path_ds):
    as_of = path_ds["decision_time"].iloc[len(path_ds) * 3 // 4].to_pydatetime()
    pm = P.train_path_models(path_ds, as_of, validate=False)
    out = pm.predict(path_ds.iloc[[0]])
    for h, p in out.items():
        assert p.shape == (3,) and np.all(p >= 0) and p.sum() == pytest.approx(1.0)


def test_expected_net_return_includes_costs():
    assert P.expected_net_return(0.5, 0.5, 4.0, 4.0, 0.45) == pytest.approx(-0.45)
    assert P.expected_net_return(0.6, 0.3, 4.0, 4.0, 0.45) == pytest.approx(0.75)


# ---------------- Drift sentinel
def test_psi_zero_for_same_distribution_and_large_for_shift():
    rng = np.random.default_rng(0)
    a, b = rng.normal(0, 1, 5000), rng.normal(0, 1, 2000)
    assert DR.psi(a, b) < 0.02
    assert DR.psi(a, rng.normal(1.5, 1, 2000)) > 0.25


def test_drift_alarm():
    rng = np.random.default_rng(1)
    ref = pd.DataFrame({f: rng.normal(0, 1, 3000) for f in "abcd"})
    same = pd.DataFrame({f: rng.normal(0, 1, 500) for f in "abcd"})
    moved = pd.DataFrame({f: rng.normal(2, 1, 500) for f in "abcd"})
    assert not DR.check(ref, same, list("abcd")).alarm
    assert DR.check(ref, moved, list("abcd")).alarm
    assert DR.check(ref, same, list("abcd"), ref_brier=0.20, recent_brier=0.26).alarm


# ---------------- Volatility regime
@pytest.mark.parametrize("trend,vol,z,expected", [
    ("TREND_UP", "NORMAL", 0.5, "STRONG_TREND"), ("RANGE", "LOW", 0.1, "RANGE"),
    ("TREND_DOWN", "HIGH", 1.0, "HIGH_VOL"), ("RANGE", "EXTREME", 1.0, "EXCEPTIONAL"),
    ("TREND_UP", "NORMAL", 7.0, "EXCEPTIONAL")])
def test_volatility_regime(trend, vol, z, expected):
    r = Regime(trend=trend, vol=vol, vol_percentile=0.5, er=0.3, vr=1.0, bars_since_break=50)
    assert volatility_regime(r, z) == expected


# ---------------- Anti-Trade
def _good(**kw):
    c = dict(direction=1, mode_live=True, data_fresh=True, vol_regime="STRONG_TREND", path_qualified=True,
             p_tp=0.6, p_sl=0.3, expected_net_return=0.8, news_calendar_connected=True, uncertainty_level="LOW")
    c.update(kw)
    return AT.TradeCandidate(**c)


def test_anti_trade_accepts_only_clean_candidate():
    assert AT.evaluate(_good()) == []


@pytest.mark.parametrize("bad", [dict(direction=0), dict(data_fresh=False), dict(vol_regime="EXCEPTIONAL"),
                                 dict(path_qualified=False), dict(expected_net_return=0.01),
                                 dict(p_tp=0.3, p_sl=0.4), dict(drift_alarm=True), dict(news_calendar_connected=False),
                                 dict(duplicate_active_signal=True), dict(uncertainty_level="HIGH"),
                                 dict(critic_vetoes=["x"])])
def test_anti_trade_rejects(bad):
    assert AT.evaluate(_good(**bad))
