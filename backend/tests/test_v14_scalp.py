"""Scalping lab: fixed rules, stop-first, costs, baseline."""
import numpy as np
import pandas as pd

from goldquant import scalp as S


def frame(n=6000, seed=2, drift=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(drift, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999, "close": c}, index=idx)


def test_target_and_stop_same_bar_counts_as_stop():
    o = np.array([100, 100, 100.0]); h = np.array([100, 101, 100.0]); l = np.array([100, 99, 100.0]); c = o.copy()
    r, how, _ = S._trade(o, h, l, c, 0, 1, 0.004, 0.0015, 3)
    assert how == "STOP" and abs(r - (-0.004 - 0.0015)) < 1e-9


def test_target_net_of_cost():
    o = np.array([100, 100.0]); h = np.array([100, 100.7]); l = np.array([100, 99.9]); c = np.array([100, 100.5])
    r, how, _ = S._trade(o, h, l, c, 0, 1, 0.004, 0.0015, 2)
    assert how == "TARGET" and abs(r - 0.005) < 1e-9  # +0.65 % gross -> +0.50 % net


def test_random_walk_does_not_qualify():
    rows = S.run_all(frame(), 0.0015)
    assert len(rows) == 6 and not any(r["qualified"] for r in rows)
    assert all(r["trades"] == r["targets"] + r["stops"] + r["timeouts"] for r in rows if r["trades"])


def test_round2_rules_run_on_random_data_and_do_not_qualify():
    d = frame(8000)
    rng = np.random.default_rng(1)
    d["volume"] = rng.lognormal(2, 0.5, len(d))
    d["taker_buy_volume"] = d["volume"] * rng.uniform(0.3, 0.7, len(d))
    d["funding"] = rng.normal(0, 0.0003, len(d))
    rows = S.run_all(d, 0.0015, rules=S.CRYPTO_RULES2, ci_level=S.CI_ROUND2)
    assert len(rows) == 8 and not any(r["qualified"] for r in rows)
    g = S.run_all(frame(8000), 0.0003, rules=S.GOLD_RULES2, ci_level=S.CI_ROUND2)
    assert len(g) == 8


def test_round3_rules_fire_once_a_day_at_fixed_utc_times():
    d = frame(8000)
    late = S.signals(d, "LATE_HOUR_LONG")
    closes = d.index[late] + pd.Timedelta(minutes=15)
    assert late.sum() > 0 and all((t.hour, t.minute) == (21, 0) for t in closes)
    mom = S.signals(d, "INTRADAY_MOMENTUM_LONG")
    assert all((t.hour, t.minute) == (22, 0) for t in d.index[mom] + pd.Timedelta(minutes=15))
    rows = S.run_all(d, 0.0015, rules=S.CRYPTO_RULES3, ci_level=S.CI_ROUND2)
    assert len(rows) == 4 and not any(r["qualified"] for r in rows)
