from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from goldquant import level_rules as LR
from goldquant import levels as L
from goldquant.engine import DecisionEngine
from goldquant.schemas import Action, Decision, LevelsBlock, Mode
from goldquant.store import Store
from goldquant.trend import market_trend


def h1_bars(closes, start="2026-01-05 00:00", spread=0.6):
    idx = pd.date_range(start, periods=len(closes), freq="60min", tz="UTC")
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + spread, "low": np.minimum(o, c) - spread, "close": c}, index=idx)


# ---------------- pivots: point-in-time
def test_pivot_known_only_after_k_bars():
    idx = pd.date_range("2026-01-05", periods=9, freq="60min", tz="UTC")
    hi_ = [10.6, 11.6, 12.6, 15.6, 13.0, 12.0, 11.0, 11.6, 12.6]
    df = pd.DataFrame({"open": 10.0, "high": hi_, "low": [9.0] * 4 + [8.0] + [9.0] * 4, "close": 10.0}, index=idx)
    p = L.pivots(df, "H1", k=3)
    hi = p[p["origin"] == -1].iloc[0]
    assert hi["price"] == pytest.approx(15.6)
    assert hi["known_at"] == df.index[6] + pd.Timedelta(hours=1)  # bar 3 confirmed at the close of bar 6


def test_levels_ignore_unconfirmed_pivots(demo_bars):
    as_of = demo_bars["M15"].index[-400] + pd.Timedelta(minutes=15)
    price = float(demo_bars["M15"]["close"].iloc[-400])
    a = L.compute_levels(demo_bars, as_of, price)  # full data, including the FUTURE relative to as_of
    # adding FUTURE bars must not change levels computed as of the same time
    b = L.compute_levels({tf: demo_bars[tf][demo_bars[tf].index < as_of] for tf in ("M15", "H1", "H4")}, as_of, price)
    assert a["supports"] == b["supports"] and a["resistances"] == b["resistances"]


def test_zone_clustering():
    piv = pd.DataFrame({"price": [100.0, 100.2, 100.3, 105.0], "tf": ["M15", "H1", "H4", "H1"],
                        "known_at": pd.to_datetime(["2026-01-05"] * 4, utc=True), "origin": [1, 1, -1, -1]})
    z = L.build_zones(piv, tol=0.5)
    assert len(z) == 2 and z[0].pivots == 3 and z[0].tfs == ("H1", "H4", "M15")


def test_supports_below_resistances_above_sorted_by_distance(demo_bars):
    as_of = demo_bars["M15"].index[-1] + pd.Timedelta(minutes=15)
    price = float(demo_bars["M15"]["close"].iloc[-1])
    r = L.compute_levels(demo_bars, as_of, price)
    s_prices = [z["price"] for z in r["supports"]]
    r_prices = [z["price"] for z in r["resistances"]]
    assert all(z["zone_high"] < price for z in r["supports"]) and all(z["zone_low"] > price for z in r["resistances"])
    assert s_prices == sorted(s_prices, reverse=True) and r_prices == sorted(r_prices)
    assert [z["name"] for z in r["supports"]] == [f"S{i + 1}" for i in range(len(s_prices))]


def test_levels_update_with_new_prices(demo_bars):
    t1 = demo_bars["M15"].index[-200]
    t2 = demo_bars["M15"].index[-1] + pd.Timedelta(minutes=15)
    cut = lambda t: {tf: demo_bars[tf][demo_bars[tf].index + pd.Timedelta(minutes=L.TF_MIN[tf]) <= t] for tf in ("M15", "H1", "H4")}  # noqa
    a = L.compute_levels(cut(t1), t1, float(cut(t1)["M15"]["close"].iloc[-1]))
    b = L.compute_levels(cut(t2), t2, float(demo_bars["M15"]["close"].iloc[-1]))
    assert [z["price"] for z in a["supports"] + a["resistances"]] != [z["price"] for z in b["supports"] + b["resistances"]]


# ---------------- features
def test_band_features_count_tests_breaks_and_flip():
    # level at ~100: tested from above twice (holds), broken, then retested from below (role flip)
    path = [105, 103, 100.5, 104, 106, 103, 100.4, 104, 105, 102, 99, 96, 94, 95, 97, 99.6, 97, 95, 94]
    df = h1_bars(path, spread=0.3)
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    a = np.full(len(df), 1.0)
    f = L.band_features(h, l, c, a, df.index, 99.8, 100.6, 0, len(df), 3, 2)
    assert f["tests"] >= 2 and f["role_flip"] == 1.0 and f["clean_breaks"] >= 1 and f["rejection"] > 0


def test_event_labels_use_future_only_after_touch(demo_bars):
    piv = pd.concat([L.pivots(demo_bars[tf], tf) for tf in ("H1", "H4")])
    ev = L.level_events(demo_bars["H1"], piv)
    assert len(ev) > 100
    assert (ev["label_known_at"] > ev["time"]).all()
    assert set(ev["hold"].unique()) <= {0, 1}


def test_validation_is_honest_on_noise():
    rng = np.random.default_rng(0)
    n = 2000
    ev = pd.DataFrame({k: rng.normal(size=n) for k in L.FEATURES})
    ev["time"] = pd.date_range("2025-01-01", periods=n, freq="2h", tz="UTC")
    ev["label_known_at"] = ev["time"] + pd.Timedelta(hours=12)
    ev["hold"] = rng.integers(0, 2, n)
    ev["tests"] = rng.integers(0, 6, n)
    assert not L.validate(ev)["validated"]


def test_validation_detects_real_signal():
    rng = np.random.default_rng(1)
    n = 3000
    ev = pd.DataFrame({k: rng.normal(size=n) for k in L.FEATURES})
    ev["time"] = pd.date_range("2025-01-01", periods=n, freq="2h", tz="UTC")
    ev["label_known_at"] = ev["time"] + pd.Timedelta(hours=12)
    ev["hold"] = (rng.uniform(size=n) < 1 / (1 + np.exp(-1.5 * ev["rejection"]))).astype(int)
    ev["tests"] = rng.integers(0, 6, n)
    v = L.validate(ev)
    assert v["validated"] and v["auc_oos"] > 0.6


def test_unvalidated_levels_never_carry_numbers():
    z = {"name": "S1", "price": 1.0, "zone_low": 0.9, "zone_high": 1.1, "strength": 70, "strength_label_ar": "قوي",
         "tests": 2, "distance_atr": -1.0}
    with pytest.raises(Exception):
        LevelsBlock(supports=[z], validated=False)
    LevelsBlock(supports=[{**z, "strength": None}], validated=False)


# ---------------- trend
def test_trend_direction_strength_and_conflict():
    up = {tf: pd.Series({"slope_ema50_atr": 0.6, "dist_ema20_atr": 1.0, "er20": 0.6}) for tf in ("M15", "M30", "H1", "H4")}
    t = market_trend(up, "STRONG_TREND")
    assert t["direction"] == "UP" and t["strength"] > 60 and t["agreement"] == 1.0
    mixed = dict(up)
    mixed["H1"] = pd.Series({"slope_ema50_atr": -0.6, "dist_ema20_atr": -1.0, "er20": 0.6})
    mixed["M15"] = pd.Series({"slope_ema50_atr": -0.6, "dist_ema20_atr": -1.0, "er20": 0.6})
    assert market_trend(mixed, "STRONG_TREND")["strength"] < t["strength"]
    assert market_trend(up, "EXCEPTIONAL")["strength"] < t["strength"]
    flat = {tf: pd.Series({"slope_ema50_atr": 0.01, "dist_ema20_atr": 0.05, "er20": 0.1}) for tf in up}
    assert market_trend(flat, "RANGE")["direction"] == "SIDEWAYS"


# ---------------- levels inside the decision
def _sr(sups, ress, validated=False):
    mk = lambda n, p, lab, st=None: {"name": n, "price": p, "zone_low": p - 0.3, "zone_high": p + 0.3, "strength": st,  # noqa
                                       "strength_label_ar": lab, "tests": 3, "distance_atr": 0.0}
    return {"supports": [mk(*s) for s in sups], "resistances": [mk(*r) for r in ress], "validated": validated, "atr_h1": 2.0}


def test_strong_resistance_before_target_vetoes_buy():
    e = LR.apply(1, 100.0, 96.0, 104.0, _sr([("S1", 98.0, "متوسط")], [("R1", 102.0, "قوي")]))
    assert e.vetoes and "R1" in e.vetoes[0]
    e2 = LR.apply(1, 100.0, 96.0, 104.0, _sr([("S1", 98.0, "متوسط")], [("R1", 102.0, "ضعيف")]))
    assert not e2.vetoes and e2.contrary
    e3 = LR.apply(1, 100.0, 96.0, 104.0, _sr([], [("R1", 106.0, "قوي")]))
    assert not e3.vetoes  # beyond the target: no effect


def test_strong_support_before_target_vetoes_sell_and_stop_checks():
    e = LR.apply(-1, 100.0, 104.0, 96.0, _sr([("S1", 98.0, "قوي")], []))
    assert e.vetoes and "S1" in e.vetoes[0]
    inside = LR.apply(1, 100.0, 98.1, 104.0, _sr([("S1", 98.0, "متوسط")], []))
    assert any("الوقف داخل" in c.text_ar for c in inside.contrary)


def test_unvalidated_levels_cannot_support_a_trade():
    sr = _sr([("S1", 98.0, "قوي")], [])
    assert not LR.apply(1, 100.0, 96.0, 104.0, sr).support
    sr_v = _sr([("S1", 98.0, "قوي", 90)], [], validated=True)
    assert LR.apply(1, 100.0, 96.0, 104.0, sr_v).support


def test_better_entry_and_reevaluation_conditions():
    e = LR.apply(1, 100.0, 96.0, 104.0, _sr([("S1", 99.0, "متوسط")], [("R1", 106.0, "ضعيف")]))
    assert e.better_entry == pytest.approx(99.3) and len(e.reevaluate_ar) == 2
    n = LR.apply(0, 100.0, None, None, _sr([("S1", 99.0, "متوسط")], [("R1", 101.0, "ضعيف")]))
    assert n.reevaluate_ar and not n.vetoes


def test_engine_decision_contains_trend_levels_and_two_sentence_reason(demo):
    eng = DecisionEngine(Store())
    d = eng.decide(demo, Mode.DEMO, (pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=7)).to_pydatetime())
    assert d.market_trend is not None and 0 <= d.market_trend.strength <= 100
    assert d.levels is not None and (d.levels.supports or d.levels.resistances)
    import re
    assert len([x for x in re.split(r"\.(?:\s|$)", d.reason_short_ar) if x.strip()]) == 2
    assert d.quote_change is not None
    Decision(**d.model_dump())
