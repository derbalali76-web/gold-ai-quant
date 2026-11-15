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
