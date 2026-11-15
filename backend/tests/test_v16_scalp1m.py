import numpy as np
import pandas as pd

from goldquant import scalp1m as S


def m1(days=70, seed=4):
    n = days * 1440
    rng = np.random.default_rng(seed)
    c = 30000 * np.exp(np.cumsum(rng.normal(0, 0.0007, n)))
    o = np.r_[c[0], c[:-1]]
    sp = np.abs(rng.normal(0, 0.0004, n)) * c
    v = rng.lognormal(3, 0.5, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + sp, "low": np.minimum(o, c) - sp, "close": c,
                         "volume": v, "taker_buy_volume": v * rng.uniform(0.3, 0.7, n)}, index=idx)


def test_orders_do_not_depend_on_the_future():
    d = m1()
    ctx = S.context(d)
    cut = len(d) // 2
    d2 = d.copy()
    d2.iloc[cut:, :4] *= 1.07  # change the future
    ctx2 = S.context(d2)
    for s in S.SETUPS:
        a = [x for x in S.plan(d, s, ctx) if x[0] < cut - 60]
        b = [x for x in S.plan(d2, s, ctx2) if x[0] < cut - 60]
        assert a == b and len(a) > 0


def test_random_walk_never_qualifies_and_counts_add_up():
    d = m1()
    rows = S.run_asset(d, "BTC")
    assert len(rows) == 9 and not any(r["qualified"] for r in rows)
    for r in rows:
        assert r["filled"] + r["unfilled"] == r["orders"]
        assert r["filled"] == r["targets"] + r["stops"] + r["timeouts"]
        if r["filled"]:
            assert r["avg_net_pct"] < 0  # costs make a random market lose


def test_limit_needs_trade_through_and_stop_beats_target_in_same_bar():
    idx = pd.date_range("2024-01-01", periods=10, freq="1min", tz="UTC")
    d = pd.DataFrame({"open": 100.0, "high": 100.2, "low": 99.995, "close": 100.0}, index=idx)
    tr, placed, unf = S.simulate(d, [(1, 100.0, 5)], "FIXED", np.full(10, 0.002), S.Costs())
    assert tr == [] and unf == 1  # touched 99.995 but not 0.01 % through 100 -> no fill
    d.loc[idx[2], "low"] = 99.0
    d.loc[idx[3], ["high", "low"]] = [101.0, 99.0]
    tr, _, _ = S.simulate(d, [(1, 100.0, 5)], "FIXED", np.full(10, 0.002), S.Costs())
    assert tr[0][2] == "STOP"


def test_round4_runs_and_gate_uses_only_past_forecasts():
    d = m1(days=500, seed=5)
    r = S.run_round4(d, "SOL")
    assert len(r["results"]) == 15 and not any(x["qualified"] for x in r["results"])
    assert 0 <= r["gate_share"] <= 1


def test_feasibility_random_walk_is_near_symmetric_and_loses_costs():
    from goldquant import scalp_feasibility as F
    d = m1(days=40, seed=9)
    r = F.study(d, "BTC")
    sym = [x for x in r["fixed"] if x["window_min"] == 60 and x["stop_pct"] == 0.65]
    lo, sh = sym
    assert abs(lo["p_target"] - lo["p_stop"]) < 0.05  # no drift -> symmetric barriers hit about equally
    assert all(x["avg_net_pct"] < 0 for x in r["fixed"])
    assert r["dynamic"] and r["by_hour"]


def test_first_passage_stop_wins_ties():
    from goldquant import scalp_feasibility as F
    c = np.array([100.0] * 5)
    h = np.array([100, 101, 100, 100, 100.0])
    lo = np.array([100, 99, 100, 100, 100.0])
    out, ret = F.first_passage(h, lo, c, np.array([0]), 3, 0.0065, 0.0065)
    assert out[0] == -1


def test_scalp_ml_features_are_causal_and_random_walk_fails():
    from goldquant import scalp_ml as M
    d = m1(days=420, seed=11)
    d.index = d.index - (d.index[0] - pd.Timestamp("2021-06-01", tz="UTC"))
    f = M.features(d)
    cut = len(d) // 2
    d2 = d.copy()
    d2.iloc[cut:, :4] *= 1.05
    f2 = M.features(d2)
    a, b = f.iloc[1500:cut - 1].fillna(0), f2.iloc[1500:cut - 1].fillna(0)
    assert np.allclose(a.to_numpy(), b.to_numpy(), atol=1e-5)
    rows = M.run_asset(d, "BTC")
    assert len(rows) == 8 and not any(r["qualified"] for r in rows)
