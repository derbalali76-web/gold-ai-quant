import numpy as np
import pandas as pd

from goldquant import hilo as HL


def _h1(n=4 * 365 * 24, seed=4):
    rng = np.random.default_rng(seed)
    vol = np.exp(np.cumsum(rng.normal(0, 0.02, n)) * 0.1) * 0.004
    r = rng.standard_t(5, n) * vol / 1.29
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.002, n)))
    lo = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.002, n)))
    idx = pd.date_range("2019-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c}, index=idx)


def test_targets_are_future_extremes_and_signs():
    h = _h1(24 * 60)
    f = HL.frame(h, "crypto", 4)
    i = 100
    want_u = 100 * np.log(h["high"].iloc[i + 1:i + 5].max() / h["close"].iloc[i])
    assert abs(f["U"].iloc[i] - want_u) < 1e-9 and (f["U"].dropna() >= -1e-12).all() and (f["D"].dropna() <= 1e-12).all()


def test_baselines_use_only_completed_windows():
    h = _h1(24 * 400)
    a = HL.frame(h, "crypto", 24)
    h2 = h.copy()
    h2.iloc[-100:, :] *= 1.3
    b = HL.frame(h2, "crypto", 24)
    k = len(h) - 100 - 24 - 2
    for c in ("b1_hi", "b1_lo", "b2_hi", "b2_lo", "rvw"):
        assert np.allclose(np.nan_to_num(a[c].iloc[:k]), np.nan_to_num(b[c].iloc[:k])), c


def test_pinball_and_evaluate():
    assert HL.pinball(np.array([1.0]), np.array([2.0]), 0.9)[0] == 0.9
    r = HL.evaluate(_h1(), "crypto", "24h")
    assert "gates" in r and 0.0 < r["holdout"]["m"]["upper_exceeded"] < 0.3
