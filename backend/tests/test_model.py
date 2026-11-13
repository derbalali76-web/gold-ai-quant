import numpy as np
import pandas as pd
import pytest

from goldquant import model as M
from goldquant.risk import breakeven_probability, compute_levels, stop_inside_structure


def _bars(rows):
    idx = pd.date_range("2026-01-05 08:00", periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def test_barrier_tp_first_sl_first_same_bar_and_timeout():
    flat = [100, 100.2, 99.8, 100]
    rows = [[100, 100, 100, 100]] + [flat] * 3
    tp_first = _bars(rows + [[100, 102.5, 99.5, 102]] + [flat] * 20)
    sl_first = _bars(rows + [[100, 100.5, 97.5, 98]] + [flat] * 20)
    both = _bars(rows + [[100, 103, 97, 100]] + [flat] * 20)
    timeout = _bars(rows + [flat] * 21)
    atr = np.full(25, 1.0)  # risk = 2.0 -> SL 98, TP 102 for a long from close 100
    for df, expected in ((tp_first, 1.0), (sl_first, 0.0), (both, 0.0), (timeout, 0.0)):
        lab, res = M.barrier_labels(df, atr, +1, horizon=16)
        assert lab[3] == expected
    lab, _ = M.barrier_labels(sl_first, atr, -1, horizon=16)
    assert lab[3] == 1.0  # short wins when price falls 2R? no: TP at 1R = 98 -> hit
    lab, _ = M.barrier_labels(tp_first, atr, +1, horizon=16)
    assert np.isnan(lab[-1]) and np.isnan(lab[-16])  # unknowable outcomes are NaN


def test_label_known_at_never_before_decision(demo_bars):
    ds = M.build_dataset(demo_bars["M15"].iloc[:4000], demo_bars["H1"], demo_bars["H4"])
    assert (ds["label_known_at"] > ds["decision_time"]).all()
    assert ((ds["label_known_at"] - ds["decision_time"]) <= pd.Timedelta(minutes=15 * M.HORIZON_BARS)).all()


def test_higher_timeframe_join_is_as_of(demo_bars):
    """H1 features at an M15 close must come from an H1 bar that had CLOSED by then."""
    t = M.build_feature_table(demo_bars["M15"].iloc[:3000], demo_bars["H1"], demo_bars["H4"])
    from goldquant.features import frame_features
    h1f = frame_features(demo_bars["H1"])
    ts = t.index[2000]
    usable = h1f[h1f.index + pd.Timedelta(minutes=60) <= ts].iloc[-1]
    assert t.loc[ts, "h1_slope_ema50_atr"] == pytest.approx(usable["slope_ema50_atr"])


def test_training_ignores_future(demo_bars):
    """Changing data after as_of must not change the model trained as of as_of."""
    m15, h1, h4 = demo_bars["M15"].iloc[:6000], demo_bars["H1"], demo_bars["H4"]
    ds = M.build_dataset(m15, h1, h4)
    as_of = ds["decision_time"].iloc[len(ds) // 2]
    tampered = ds.copy()
    future = tampered["decision_time"] > as_of
    tampered.loc[future, "label"] = 1 - tampered.loc[future, "label"]
    a, b = M.train_as_of(ds, as_of), M.train_as_of(tampered, as_of)
    x = ds[M.FEATURES].iloc[:50]
    np.testing.assert_allclose(a.model.predict_proba(x.to_numpy()), b.model.predict_proba(x.to_numpy()))


def test_walk_forward_reports_honest_baseline(demo_bars):
    ds = M.build_dataset(demo_bars["M15"], demo_bars["H1"], demo_bars["H4"])
    rep = M.purged_walk_forward(ds)
    assert rep.folds >= 3 and rep.n_oos > 1000
    assert 0 < rep.base_rate < 1 and 0 < rep.brier_model < 1
    for s in rep.selective:
        if s["signals"] < 300:
            assert s["low_sample_warning"]


def test_wilson_interval():
    lo, hi = M.wilson(95, 100)
    assert lo < 0.95 < hi and lo > 0.88


def test_risk_levels_and_breakeven():
    lv = compute_levels(+1, 2000.0, 2.0)
    assert lv.stop_loss < lv.entry_min < lv.entry_max < lv.tp1 < lv.tp2 < lv.tp3
    sv = compute_levels(-1, 2000.0, 2.0)
    assert sv.tp3 < sv.tp2 < sv.tp1 < sv.entry_min < sv.entry_max < sv.stop_loss
    assert breakeven_probability(4.0, 4.0, 0.0) == pytest.approx(0.5)
    assert breakeven_probability(4.0, 4.0, 0.45) > 0.5
    assert compute_levels(+1, 2000.0, 0.0) is None
    assert stop_inside_structure(+1, stop=1996, swing_low=1995, swing_high=2010)
    assert not stop_inside_structure(+1, stop=1994, swing_low=1995, swing_high=2010)
