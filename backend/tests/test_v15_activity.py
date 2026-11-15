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


def test_api_shows_activity_only_for_qualified_coins(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    from goldquant.api import create_app, Settings
    from goldquant import crypto_engine as CE
    monkeypatch.setenv("GOLDQUANT_BG_REFRESH", "0")
    monkeypatch.delenv("GOLDQUANT_TOKEN", raising=False)
    hist = frame(6000)
    params = A.export(hist, {"qualified": True, "skill": 0.2, "holdout_skill": 0.1, "period": "x"})
    (tmp_path / "activity_models.json").write_text(json.dumps(
        {"assets": {"BTC": {"model": params}, "ETH": {"model": None}}}), encoding="utf-8")
    rng = np.random.default_rng(9)

    class Feed:
        def bars(self, sym, tf, as_of, limit=1000):
            m = {"M15": 15, "M30": 30, "H1": 60, "H4": 240, "1d": 1440}[tf]
            idx = pd.date_range(end=pd.Timestamp(as_of).floor(f"{m}min") - pd.Timedelta(minutes=m), periods=1000,
                                freq=f"{m}min", tz="UTC")
            c = 3000 * np.exp(np.cumsum(rng.normal(0, 0.002, len(idx))))
            o = np.r_[c[0], c[:-1]]
            return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999,
                                 "close": c, "volume": 1.0 + rng.random(len(idx)), "tick_volume": 1.0,
                                 "taker_buy_volume": 0.5}, index=idx)
    monkeypatch.setattr(CE, "CryptoFeed", Feed)
    c = TestClient(create_app(str(tmp_path / "g.db"), settings=Settings.from_env(str(tmp_path))))
    b = c.get("/decision?asset=BTC").json()
    assert b["scalp_activity"] is not None and b["scalp_activity"]["level"] in ("HIGH", "NORMAL", "LOW")
    assert b["action"] == "WAIT"  # activity never turns into a trade signal
    assert c.get("/decision?asset=ETH").json()["scalp_activity"] is None
