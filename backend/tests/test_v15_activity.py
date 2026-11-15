import numpy as np
import pandas as pd

from goldquant import activity as A


def frame(n=12000, seed=3):
    rng = np.random.default_rng(seed)
    vol = np.exp(np.sin(np.arange(n) / 500) * 0.8) * 0.002  # volatility clusters -> predictable activity
    c = 100 * np.exp(np.cumsum(rng.normal(0, vol)))
    idx = pd.date_range("2021-01-01", periods=n, freq="15min", tz="UTC")
    o = np.r_[c[0], c[:-1]]
    sp = np.abs(rng.normal(0, vol)) * c
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + sp, "low": np.minimum(o, c) - sp, "close": c,
                         "volume": rng.lognormal(2, 0.3, n)}, index=idx)


def test_labels_look_only_forward_and_end_nan():
    d = frame(2000)
    y = A.labels(d)
    assert np.isnan(y[-1]) and np.isfinite(y[:-A.HORIZON - 1]).all()
    d2 = d.copy()
    d2.iloc[:500, :4] *= 1.5  # changing the past must not change later labels
    assert np.array_equal(A.labels(d2)[600:-20], y[600:-20])


def test_export_predict_roundtrip_only_when_qualified():
    d = frame()
    params = A.export(d, {"qualified": True})
    p = A.predict(params, d.iloc[-1000:])
    assert p is not None and 0 <= p["probability"] <= 1 and 0 <= p["usual"] <= 1
    assert A.predict(dict(params, qualified=False), d.iloc[-1000:]) is None
