import numpy as np
import pandas as pd

from goldquant import paxg_study as PS


def _pair(n_days=900, seed=2):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-01", periods=24 * n_days, freq="h", tz="UTC")
    x = 2000 * np.exp(np.cumsum(rng.normal(0, 0.002, len(idx))))
    paxg = pd.DataFrame({"close": x * np.exp(rng.normal(0, 0.002, len(idx)))}, index=idx)
    gold = idx[(idx.dayofweek < 4) | ((idx.dayofweek == 4) & (idx.hour < 21)) | ((idx.dayofweek == 6) & (idx.hour >= 22))]
    xau = pd.DataFrame({"open": x[idx.get_indexer(gold)], "close": x[idx.get_indexer(gold)]}, index=gold)
    return paxg, xau


def test_weekend_frame_uses_friday_close_and_reopen():
    paxg, xau = _pair(60)
    w = PS.weekend_frame(paxg, xau)
    assert len(w) >= 7 and (w.index.dayofweek == 6).all()  # reopen on Sunday evening


def test_premium_z_uses_only_the_past():
    paxg, xau = _pair(200)
    a = PS.premium_frame(paxg, xau)
    paxg2 = paxg.copy()
    paxg2.iloc[-200:] *= 1.1
    b = PS.premium_frame(paxg2, xau)
    k = len(a) - 400
    assert np.allclose(a["z"].iloc[:k].fillna(0), b["z"].iloc[:k].fillna(0))


def test_tests_report_gates():
    paxg, xau = _pair()
    assert "gates" in PS.premium_test(paxg, xau)
    r = PS.weekend_test(paxg, xau)
    assert r["weekends"] > 100 and ("gates" in r or r["reason"])
