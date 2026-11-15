"""Crypto: archive parsing (ms / µs timestamps), storage round trip, 24/7 planner with flow features."""
import io
import zipfile

import numpy as np
import pandas as pd

from goldquant import crypto_store as CS
from goldquant import planner as P
from goldquant.providers import binance_archive as BA


def _zip(text):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x.csv", text)
    return b.getvalue()


def test_parse_klines_ms_and_us_and_header():
    ms = "1704067200000,42000,42100,41900,42050,12.5,1704070799999,525000,100,7.5,315000,0\n"
    us = "1735689600000000,93000,93500,92800,93400,3.2,1735693199999999,298000,50,1.1,102000,0\n"
    hdr = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n" + ms
    a, b, c = (BA.parse_klines_zip(_zip(t)) for t in (ms, us, hdr))
    assert str(a.index[0]) == "2024-01-01 00:00:00+00:00" and a["taker_buy_volume"].iloc[0] == 7.5
    assert str(b.index[0]) == "2025-01-01 00:00:00+00:00"
    assert c.equals(a)


def test_parse_funding():
    t = "calc_time,funding_interval_hours,last_funding_rate\n1704067200000,8,0.0001\n1704096000000,8,-0.00005\n"
    f = BA.parse_funding_zip(_zip(t))
    assert list(f["funding"]) == [0.0001, -0.00005]


def _walk(n=3000, seed=4):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    c = 40000 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    o = np.r_[c[0], c[:-1]]
    v = rng.lognormal(3, 0.4, n)
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.002, "low": np.minimum(o, c) * 0.998, "close": c,
                         "volume": v, "taker_buy_volume": v * rng.uniform(0.3, 0.7, n)}, index=idx)


def test_store_round_trip(tmp_path):
    d = _walk(800)
    CS.save_bars(tmp_path, "BTCUSDT", "1h", d)
    back = CS.load_bars(tmp_path, "BTCUSDT", "1h")
    assert len(back) == len(d) and np.allclose(back["close"], d["close"], rtol=1e-6)
    assert CS.save_bars(tmp_path, "BTCUSDT", "1h", d) == 0  # unchanged -> no rewrite


def test_flow_features_point_in_time_and_weekend_trading_allowed():
    d = _walk(600)
    fund = pd.DataFrame({"funding": np.linspace(-1e-4, 1e-4, 80)}, index=pd.date_range("2024-01-01", periods=80, freq="8h", tz="UTC"))
    f1 = P.flow_features(d, fund).iloc[300]
    d2 = d.copy(); d2.iloc[301:, :] *= 1.3
    f2 = P.flow_features(d2, fund).iloc[300]
    pd.testing.assert_series_equal(f1, f2)
    # funding published at 08:00 is usable for the bar 07:00-08:00 (close 08:00), not for 06:00-07:00
    assert P.flow_features(d, fund).loc["2024-01-01 07:00", "funding"] == fund["funding"].iloc[1]
    assert P.flow_features(d, fund).loc["2024-01-01 06:00", "funding"] == fund["funding"].iloc[0]


def test_crypto_walk_forward_runs_with_crypto_cost():
    d = _walk(4200)
    r = P.walk_forward(d, "HOURS", cols=P.FEATURES + P.INTRADAY + ["vol_z", "taker20", "taker_imb"], asset="BTCUSDT")
    assert r.decision_days > 0  # weekends are tradable for crypto (no weekend mask)
    assert P.COST == P.ASSET_COST["XAUUSD"]  # restored after the run


def test_crypto_job_downloads_and_researches(tmp_path, monkeypatch):
    import importlib.util, sys
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("cloud_job", Path(__file__).resolve().parents[1] / "tools" / "cloud_job.py")
    cj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cj)
    monkeypatch.setattr(cj, "MD", tmp_path / "md")
    monkeypatch.setattr(cj, "MODELS", tmp_path / "models")
    monkeypatch.setattr(cj, "CRYPTO_START", {"BTCUSDT": (2025, 11)})
    full = _walk(24 * 400)
    full.index = pd.date_range("2025-11-01", periods=len(full), freq="h", tz="UTC")

    class FakeArc:
        errors = []
        def klines_month(self, sym, tf, y, m):
            part = full[(full.index.year == y) & (full.index.month == m)]
            return part if tf == "1h" else part.resample("1D").agg({"open": "first", "high": "max", "low": "min",
                                                                     "close": "last", "volume": "sum", "taker_buy_volume": "sum"})
        def klines_day(self, sym, tf, d):
            return pd.DataFrame()
        def metrics_day(self, sym, d):
            idx = pd.date_range(pd.Timestamp(d, tz="UTC"), periods=24, freq="h")
            return pd.DataFrame({"oi": np.linspace(100, 120, 24), "top_ls_ratio": 1.1, "taker_ls_ratio": 1.0}, index=idx)
        def funding_month(self, sym, y, m):
            return pd.DataFrame({"funding": [1e-4, -1e-4]}, index=pd.DatetimeIndex(
                [pd.Timestamp(y, m, 1, tz="UTC"), pd.Timestamp(y, m, 2, tz="UTC")]))
    import goldquant.providers.binance_archive as BAm
    monkeypatch.setattr(BAm, "BinanceArchive", FakeArc)
    from datetime import date as _d
    class D(_d):
        @classmethod
        def today(cls):
            return _d(2026, 12, 3)
    monkeypatch.setattr(cj, "date", D)
    cj.crypto()
    h1 = CS.load_bars(tmp_path / "md", "BTCUSDT", "1h")
    assert len(h1) > 8000
    cj.MODELS.mkdir(parents=True, exist_ok=True)
    rep = cj.crypto_research()
    assert "BTCUSDT" in rep["assets"] and "HOURS" in rep["assets"]["BTCUSDT"]


def test_crypto_engine_analysis_only(monkeypatch):
    from datetime import datetime, timezone
    from goldquant import crypto_engine as CE
    now = datetime(2026, 11, 15, 12, 7, tzinfo=timezone.utc)  # a Sunday: crypto trades, nothing is "closed"
    rng = np.random.default_rng(5)

    def frame(step_min, n):
        idx = pd.date_range(end=pd.Timestamp(now).floor(f"{step_min}min") - pd.Timedelta(minutes=step_min), periods=n,
                            freq=f"{step_min}min", tz="UTC")
        c = 90000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
        o = np.r_[c[0], c[:-1]]
        v = rng.lognormal(2, 0.3, n)
        return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999, "close": c,
                             "volume": v, "tick_volume": v, "taker_buy_volume": v / 2}, index=idx)

    class Feed:
        def bars(self, sym, tf, as_of, limit=1000):
            return frame({"M15": 15, "M30": 30, "H1": 60, "H4": 240, "1d": 1440}[tf], 1000)

    d = CE.decide("BTC", Feed(), now)
    assert d.instrument == "BTC/USD" and d.action.value == "WAIT" and not d.market_closed
    assert d.market_trend is not None and d.levels is not None and d.data_health is not None
    assert all(not o.validated and o.action.value == "WAIT" for o in d.outlooks)
    assert all(o.plan is None or not o.plan.recommendation for o in d.outlooks)
    assert next(c for c in d.outlooks[0].checklist if c.code == "session").ok is True


def test_public_snapshot_for_crypto(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from goldquant.api import create_app, Settings
    from goldquant import crypto_engine as CE
    monkeypatch.setenv("GOLDQUANT_BG_REFRESH", "0")
    rng = np.random.default_rng(9)

    class Feed:
        def bars(self, sym, tf, as_of, limit=1000):
            m = {"M15": 15, "M30": 30, "H1": 60, "H4": 240, "1d": 1440}[tf]
            idx = pd.date_range(end=pd.Timestamp(as_of).floor(f"{m}min") - pd.Timedelta(minutes=m), periods=600,
                                freq=f"{m}min", tz="UTC")
            c = 3000 * np.exp(np.cumsum(rng.normal(0, 0.002, len(idx))))
            o = np.r_[c[0], c[:-1]]
            return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999,
                                 "close": c, "volume": 1.0, "tick_volume": 1.0, "taker_buy_volume": 0.5}, index=idx)
    monkeypatch.setattr(CE, "CryptoFeed", Feed)
    c = TestClient(create_app(str(tmp_path / "g.db"), settings=Settings.from_env(str(tmp_path))))
    s = c.get("/public/snapshot?asset=ETH").json()
    assert s["asset"] == "ETH" and s["recommendations"] == [] and len(s["bars"]["H1"]) == 120 and s["cost"] > 0
    assert c.get("/public/snapshot?asset=DOGE").status_code == 422


def test_parse_metrics_hourly_known_at_bar_close():
    t = ("create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
         "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
         "2024-01-01 00:05:00,BTCUSDT,100,1,1,1.2,1,0.9\n2024-01-01 01:00:00,BTCUSDT,110,1,1,1.3,1,1.1\n"
         "2024-01-01 01:05:00,BTCUSDT,120,1,1,1.4,1,1.0\n")
    m = BA.parse_metrics_zip(_zip(t))
    # 00:05 .. 01:00 -> bar 00:00 (last = 01:00 snapshot, known at the bar's close)
    assert m.loc["2024-01-01 00:00", "oi"] == 110 and m.loc["2024-01-01 01:00", "oi"] == 120


def test_crypto_big_genuine_jump_warns_but_does_not_block():
    from datetime import datetime, timezone
    from goldquant import crypto_engine as CE
    now = datetime(2026, 11, 15, 6, 7, tzinfo=timezone.utc)
    rng = np.random.default_rng(3)

    class Feed:
        def bars(self, sym, tf, as_of, limit=1000):
            m = {"M15": 15, "M30": 30, "H1": 60, "H4": 240, "1d": 1440}[tf]
            idx = pd.date_range(end=pd.Timestamp(now).floor(f"{m}min") - pd.Timedelta(minutes=m), periods=800,
                                freq=f"{m}min", tz="UTC")
            r = rng.normal(0, 0.001, len(idx))
            r[-20] = 0.09  # a 9 % liquidation candle
            c = 3000 * np.exp(np.cumsum(r))
            o = np.r_[c[0], c[:-1]]
            return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.0005, "low": np.minimum(o, c) * 0.9995,
                                 "close": c, "volume": 1.0, "tick_volume": 1.0, "taker_buy_volume": 0.5}, index=idx)
    d = CE.decide("ETH", Feed(), now)
    assert d.action.value == "WAIT" and d.data_health.status == "WARN"
