"""AI QUANT Trade Engine simulator: fills, exits, intrabar ordering and costs on hand-built bars."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from trade_engine.sim import Costs, Market, Order, simulate, run  # noqa: E402

T0 = pd.Timestamp("2025-01-01 00:00", tz="UTC")
ZERO = Costs(0.0, 0.0, 0.0, 0.0)


def bars(rows, step="1h", start=T0):
    idx = pd.date_range(start, periods=len(rows), freq=step, tz="UTC")
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close"])


def flat(n, p=100.0, step="1h", start=T0):
    return bars([[p, p, p, p]] * n, step, start)


def mk(rows, pad=200):
    """Hourly bars from T0, then a long flat tail so every order has data for its whole life."""
    df = pd.concat([bars(rows), flat(pad, rows[-1][3], start=T0 + pd.Timedelta(hours=len(rows)))])
    return Market(None, df)


def test_limit_needs_a_trade_strictly_below():
    m = mk([[101, 101, 100, 100.5]])  # touches 100, never trades below
    r = simulate(Order(T0, target=110, stop=90, limit=100), m, ZERO)
    assert r.outcome == "NOT_FILLED" and not r.filled and r.net == 0


def test_limit_fill_then_target_in_a_later_bar_net_of_fees():
    m = mk([[101, 101, 99.5, 100], [100, 111, 100, 110]])
    c = Costs(maker=0.001, taker=0.001, half_spread=0.0, slippage=0.0)
    r = simulate(Order(T0, target=110, stop=90, limit=100), m, c)
    assert r.outcome == "TARGET" and r.entry == 100 and r.exit == 110
    assert r.net == pytest.approx(110 * 0.999 / (100 * 1.001) - 1, abs=1e-6)


def test_target_not_allowed_in_the_fill_bar_but_stop_is():
    m = mk([[101, 120, 99, 100]])  # fill bar reaches the target: not counted; flat afterwards -> time exit
    r = simulate(Order(T0, target=110, stop=90, limit=100, hold_bars=1), m, ZERO)
    assert r.outcome == "TIME"
    m2 = mk([[101, 101, 85, 95]])  # fill bar goes on to the stop: counted
    r2 = simulate(Order(T0, target=110, stop=90, limit=100), m2, ZERO)
    assert r2.outcome == "STOP" and r2.exit == 90


def test_both_levels_in_one_bar_counts_as_stop():
    m = mk([[101, 101, 99, 100], [100, 115, 85, 100]])
    r = simulate(Order(T0, target=110, stop=90, limit=100), m, ZERO)
    assert r.outcome == "STOP"


def test_gap_through_stop_fills_at_open_with_slippage():
    m = mk([[101, 101, 99, 100], [80, 82, 79, 81]])
    c = Costs(0.0, 0.0, 0.0, 0.01)
    r = simulate(Order(T0, target=110, stop=90, limit=100), m, c)
    assert r.outcome == "STOP" and r.exit == pytest.approx(80 * 0.99)


def test_limit_fills_at_a_lower_open():
    m = mk([[97, 98, 96, 97], [97, 120, 97, 115]])
    r = simulate(Order(T0, target=110, stop=90, limit=100), m, ZERO)
    assert r.entry == 97 and r.outcome == "TARGET" and r.exit == 110


def test_market_entry_pays_spread_slippage_and_taker():
    m = mk([[100, 100, 100, 100]])
    c = Costs(maker=0.0, taker=0.001, half_spread=0.0005, slippage=0.0005)
    r = simulate(Order(T0, target=110, stop=90, limit=None, hold_bars=1), m, c)
    assert r.entry == pytest.approx(100.1)
    assert r.outcome == "TIME" and r.exit == pytest.approx(100 * 0.999)
    assert r.net == pytest.approx(100 * 0.999 * 0.999 / (100.1 * 1.001) - 1, abs=1e-6)


def test_time_exit_after_hold_bars_and_no_data_at_the_edge():
    m = mk([[101, 101, 99, 100]] + [[100, 101, 99, 100]] * 30, pad=0)
    r = simulate(Order(T0, target=110, stop=90, limit=100, hold_bars=2), m, ZERO)
    assert r.outcome == "TIME" and r.bars_held <= 3
    assert simulate(Order(T0, target=110, stop=90, limit=100, hold_bars=30), m, ZERO).outcome == "NO_DATA"


def test_fifteen_minute_bars_take_over_where_available():
    h1 = flat(300, 100)
    q = bars([[100, 100, 99, 99.5], [99.5, 99.6, 89, 89.5]] + [[89.5] * 4] * 100, "15min", T0)
    m = Market(q, h1)
    r = simulate(Order(T0, target=110, stop=90, limit=100), m, ZERO)
    assert r.fill_time.startswith("2025-01-01 00:00") and r.outcome == "STOP"


def test_one_position_at_a_time():
    m = mk([[101, 101, 99, 100]] + [[100, 100.5, 99.5, 100]] * 100)
    orders = [Order(T0 + k * pd.Timedelta(hours=4), target=110, stop=90, limit=100, hold_bars=2) for k in range(4)]
    rs = run(orders, m, ZERO)
    assert len(rs) < 4 and all(r.filled or r.outcome == "NOT_FILLED" for r in rs)


def test_rule_family_is_the_registered_24_and_holdout_is_sealed(monkeypatch):
    from trade_engine import rules
    cs = rules.configs()
    assert len(cs) == 24 and len({c["id"] for c in cs}) == 24
    monkeypatch.delenv("TE_UNSEAL_HOLDOUT", raising=False)
    f = pd.DataFrame({"t": [rules.HOLDOUT_START]})
    with pytest.raises(PermissionError):
        rules.orders(f, cs[0], rules.DEV_START, rules.HOLDOUT_END)


def test_features_at_t_do_not_change_when_future_bars_arrive():
    import numpy as np
    from trade_engine import rules
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 600)))
    idx = pd.date_range("2024-01-01", periods=600, freq="4h", tz="UTC")
    h4 = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": rng.uniform(1, 2, 600)}, index=idx)
    full, cut = rules.features(h4), rules.features(h4.iloc[:450])
    common = cut.index
    pd.testing.assert_frame_equal(full.loc[common], cut, check_exact=False, rtol=1e-12)


def test_holm_and_brier_skill_and_month_bootstrap():
    import numpy as np
    from trade_engine.phase2 import holm
    from trade_engine.metrics import brier_skill, month_block_boot
    assert holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
    y = np.array([1, 0, 1, 1.0]); base = np.full(4, 0.75)
    assert brier_skill(base, base, y) == 0.0 and brier_skill(y, base, y) == 1.0
    months = np.array(["2024-%02d" % (i % 12 + 1) for i in range(48)])
    ci = month_block_boot(months, np.ones(48) * 0.01, np.mean)
    assert ci == (0.01, 0.01)


def test_te_collector_parses_archive_and_drops_duplicates():
    import io, zipfile
    from trade_engine.collect import parse, months
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", "calc_time,funding_interval_hours,last_funding_rate\n"
                            "1733011200000,8,0.0001\n1733040000000,8,0.0002\n1733040000000,8,0.0003\n")
    assert parse(buf.getvalue()) == [(1733011200000, 0.0001), (1733040000000, 0.0003)]
    assert list(months(2024, 11, (2025, 1))) == [(2024, 11), (2024, 12), (2025, 1)]  # December included


def _res(t, net, filled=True, outcome="TARGET"):
    from trade_engine.sim import Result
    return Result(str(pd.Timestamp(t, tz="UTC")), filled, outcome if filled else "NOT_FILLED", net=net)


def test_v2_random_and_ablation_tests_behave():
    import numpy as np
    from trade_engine import phase2_v2 as P
    rng = np.random.default_rng(0)
    nets = np.concatenate([np.full(500, -0.01), np.full(10, np.inf)])
    p_hi, _ = P.p_random(nets, 50, 0.02, rng)
    p_lo, _ = P.p_random(nets, 50, -0.05, rng)
    assert p_hi < 0.01 and p_lo > 0.99
    strata = np.array(["a"] * 255 + ["b"] * 255)
    p_s, _ = P.p_random(nets, 20, 0.02, rng, strata, ["a"] * 20)
    assert p_s < 0.01
    days = pd.date_range("2022-01-01", periods=400, freq="3D")
    good = [_res(t, 0.02) for t in days]
    bad = [_res(t, -0.01) for t in days]
    p_ab, d = P.p_ablation(good, bad, rng)
    assert p_ab < 0.01 and d == 3.0
    assert P.p_ablation(bad, good, rng)[0] > 0.99


def test_v2_signals_use_only_trailing_information():
    from trade_engine import rules_v2 as R
    s = pd.Series(range(100), index=pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC"), dtype=float)
    full, cut = R._trail_pct(s, 30), R._trail_pct(s.iloc[:60], 30)
    pd.testing.assert_series_equal(full.iloc[:60], cut)
    assert len(R.configs()) == 12
