import numpy as np
import pandas as pd

from goldquant import price_range as PR


def _h1(n=4 * 365 * 24, seed=3):
    rng = np.random.default_rng(seed)
    vol = np.exp(np.cumsum(rng.normal(0, 0.02, n)) * 0.1) * 0.004
    r = rng.standard_t(5, n) * vol / 1.29
    c = 100 * np.exp(np.cumsum(r))
    idx = pd.date_range("2019-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c}, index=idx)


def test_interval_score_formula():
    s = PR.interval_score(np.array([-1.0, -1.0, -1.0]), np.array([1.0, 1.0, 1.0]), np.array([0.0, 2.0, -1.5]))
    assert s.tolist() == [2.0, 2.0 + 10 * 1.0, 2.0 + 10 * 0.5]


def test_baseline_uses_only_completed_returns():
    h1 = _h1(24 * 400)
    f = PR.frame(h1, "crypto", 24)
    # changing the future must not change any baseline or feature known at an earlier origin
    h2 = h1.copy()
    h2.iloc[-100:, :] *= 1.5
    g = PR.frame(h2, "crypto", 24)
    cut = len(h1) - 100 - 24 - 2
    for k in ("b1_lo", "b1_hi", "b2_lo", "b2_hi", "rv4", "rvd", "rvw", "rvm"):
        a, b = f[k].iloc[:cut].to_numpy(), g[k].iloc[:cut].to_numpy()
        assert np.allclose(np.nan_to_num(a), np.nan_to_num(b)), k


def test_evaluate_runs_and_reports_gates():
    rep = PR.evaluate(_h1(), "crypto", "24h", events=["2022-06-15T18:00:00Z", "2022-07-27T18:00:00Z"])
    assert set(rep["gates"]) and "walk_forward" in rep and rep["holdout"]["m"]["n"] > 100
    assert 0.6 < rep["holdout"]["m"]["coverage"] < 0.95
    assert rep["events"] is None or rep["events"]["windows"] > 0


def test_export_and_live_interval_brackets_the_last_close():
    h1 = _h1()
    p = PR.export(h1, "crypto", "4h")
    assert p and p["q10"] < 0 < p["q90"] and len(p["beta"]) == len(p["cols"]) + 1
    r = PR.live(p, h1, now=h1.index[-1] + pd.Timedelta(hours=1))
    assert r["low"] < r["close_at_issue"] < r["high"]
    # a bar that is still forming is ignored
    r2 = PR.live(p, h1, now=h1.index[-1] + pd.Timedelta(minutes=30))
    assert r2["close_at_issue"] == float(h1["close"].iloc[-2])
    assert PR.display_horizon({"24h": False, "4h": True}) == "4h" and PR.display_horizon({}) is None


def test_range_endpoint_shape_and_validation():
    from fastapi.testclient import TestClient
    from goldquant.api import create_app
    c = TestClient(create_app(":memory:"))
    assert c.get("/range", params={"asset": "DOGE"}).status_code == 422
    r = c.get("/range", params={"asset": "XAU"}).json()
    assert set(r) >= {"asset", "available", "display", "horizons"}
    for h, v in r["horizons"].items():  # only qualified horizons, each with an interval around the issue close
        assert h in ("4h", "24h") and v["low"] < v["high"]


def test_due_slot_is_the_latest_recordable_issue_time():
    ts = pd.Timestamp
    assert PR.due_slot(ts("2026-11-17T00:00:10Z")) == ts("2026-11-17T00:00Z")
    assert PR.due_slot(ts("2026-11-17T01:05Z")) == ts("2026-11-17T00:00Z")  # the 00:00 run was missed: still open
    assert PR.due_slot(ts("2026-11-17T01:16Z")) is None  # 76 minutes: closed
    assert PR.due_slot(ts("2026-11-17T03:00Z")) is None
    assert PR.due_slot(ts("2026-11-17T20:59Z")) == ts("2026-11-17T20:00Z")


def test_late_issue_uses_only_bars_closed_at_the_issue_time():
    h1 = _h1()
    p = PR.export(h1, "crypto", "4h")
    slot = h1.index[-3] + pd.Timedelta(hours=1)
    on_time = PR.live(p, h1.iloc[:-2], now=slot)
    late = PR.live(p, h1, now=slot)  # later bars exist but are not used
    assert on_time == late and pd.Timestamp(late["issued_at"]) == slot


def test_snapshot_adds_the_missed_issue_time_only_with_older_parameters():
    h1 = _h1()
    p = PR.export(h1, "crypto", "4h")
    while (h1.index[-1] + pd.Timedelta(hours=1)).hour % 4 != 1:  # latest bar closes one hour after an issue time
        h1 = h1.iloc[:-1]
    last_close = h1.index[-1] + pd.Timedelta(hours=1)
    slot, now = last_close - pd.Timedelta(hours=1), last_close + pd.Timedelta(minutes=2)
    assert PR.due_slot(now) == slot
    compute = lambda t: [r for r in [PR.live(p, h1, pd.Timestamp(t))] if r]  # noqa: E731
    both = PR.with_due_slot(now, compute, slot - pd.Timedelta(days=2))
    assert [pd.Timestamp(r["issued_at"]) for r in both] == [last_close, slot]
    assert both[1] == PR.live(p, h1.iloc[:-1], slot)  # exactly the on-time computation
    assert len(PR.with_due_slot(now, compute, slot + pd.Timedelta(minutes=1))) == 1  # newer parameters: not used
    assert len(PR.with_due_slot(now, compute, None)) == 1
