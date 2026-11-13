import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from goldquant import backtest as BT
from goldquant.api import create_app
from goldquant.engine import DecisionEngine
from goldquant.reliability import adversarial as ADV
from goldquant.reliability import integrity as INT
from goldquant.reliability import uncertainty_budget as UB
from goldquant.reliability.execution import ExecutionModel
from goldquant.reliability.governance import SAFE_MODE, ModelRegistry
from goldquant.reliability.shadow import ShadowBook
from goldquant.schemas import Action, Mode
from goldquant.store import Store


# ---------------- Execution reality
def test_execution_model_costs():
    em = ExecutionModel()
    assert em.spread("ASIA", 1.0) > em.spread("LONDON_NY_OVERLAP", 1.0)
    assert em.spread("NEW_YORK", 2.0) == pytest.approx(2 * em.spread("NEW_YORK", 1.0))
    assert all(em.slippage(2.0) >= em.slippage_base for _ in range(50))
    delays = [em.entry_delay_bars() for _ in range(2000)]
    assert set(delays) <= {1, 2} and 0.02 < delays.count(2) / 2000 < 0.15
    assert not em.limit_filled(1, 100.0, 99.95, 101, 0.3) and em.limit_filled(1, 100.0, 99.8, 101, 0.3)


def test_realistic_execution_is_not_cheaper(demo_bars):
    a = BT.run(demo_bars["M15"], demo_bars["H1"], demo_bars["H4"])
    b = BT.run(demo_bars["M15"], demo_bars["H1"], demo_bars["H4"], execution=ExecutionModel())
    assert "spread_by_session" in b["costs"]
    if a["baseline"]["trades"] and b["baseline"]["trades"]:
        assert b["baseline"]["ev_per_trade"] <= a["baseline"]["ev_per_trade"] + 0.05


# ---------------- Uncertainty budget
def _ub(**kw):
    a = dict(quote_age_s=10, max_age_s=180, n_missing_critical=0, n_firewall_warnings=0, qualified=True,
             calibration_passed=True, ece=0.01, drift_alarm=False, analog_novelty=0.6, vol_percentile=0.5,
             bars_since_break=50, disagreement=0.03)
    a.update(kw)
    return UB.compute(**a)


def test_budget_within_for_clean_state():
    r = _ub()
    assert r.within and r.used < r.limit


@pytest.mark.parametrize("bad", [dict(qualified=False), dict(drift_alarm=True), dict(quote_age_s=None),
                                 dict(n_missing_critical=4), dict(disagreement=0.5),
                                 dict(vol_percentile=0.99, analog_novelty=1.6, bars_since_break=1)])
def test_budget_exceeded(bad):
    assert not _ub(**bad).within


def test_engine_reports_budget(demo):
    d = DecisionEngine(Store()).decide(demo, Mode.DEMO, (pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=5)).to_pydatetime())
    if d.uncertainty is not None:
        assert d.uncertainty.budget_used is not None and set(d.uncertainty.budget_components) == set(UB.WEIGHTS)


# ---------------- Governance & rollback
def test_registry_activation_needs_gate_and_rollback(tmp_path):
    reg = ModelRegistry(tmp_path / "r.json")
    reg.register("v1", {"brier": 0.6}, gate_passed=True)
    reg.register("v2", {"brier": 0.58}, gate_passed=True)
    reg.register("v3", {}, gate_passed=False)
    assert not reg.activate("v3")
    assert reg.activate("v1") and reg.activate("v2") and reg.active == "v2"
    bad = {"closed": 80, "brier_live": 0.75, "total_pnl": -10, "win_rate_ci95": [0.2, 0.4]}
    r = reg.monitor(bad, 0.6, False)
    assert r["action"] == "rollback" and reg.active == "v1"
    r = reg.monitor(bad, 0.6, False)
    assert r["action"] == "safe_mode" and reg.safe_mode
    assert ModelRegistry(tmp_path / "r.json").safe_mode  # persisted


def test_registry_ignores_small_samples(tmp_path):
    reg = ModelRegistry(tmp_path / "r.json")
    reg.register("v1", {}, True)
    reg.activate("v1")
    assert reg.monitor({"closed": 10, "brier_live": 0.9, "total_pnl": -5, "win_rate_ci95": [0, 0.3]}, 0.6, False)["action"] == "none"


def test_safe_mode_blocks_trades(demo, monkeypatch, tmp_path):
    import goldquant.engine as E
    from goldquant.engine import PathState
    reg = ModelRegistry(tmp_path / "r.json")
    reg.state["active"] = SAFE_MODE
    seen = {}
    real = E.anti_trade
    monkeypatch.setattr(E, "anti_trade", lambda c: (seen.setdefault("v", list(c.critic_vetoes)), real(c))[1])
    eng = DecisionEngine(Store(), registry=reg)
    for h in range(0, 60, 6):
        d = eng.decide(demo, Mode.DEMO, (pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=h)).to_pydatetime())
        assert d.action in (Action.WAIT, Action.UNAVAILABLE)
    assert any("وضع الأمان" in v for v in seen.get("v", ["وضع الأمان"]))


# ---------------- Shadow tournament
def test_shadow_book_scores_rules_without_acting():
    sb = ShadowBook()
    t0 = pd.Timestamp("2026-01-05 10:00", tz="UTC")
    sb.record("a", t0, 1, 100.0, 2.0, 1.0, 240, {"acc_meta": True, "acc_baseline": True})
    sb.record("b", t0, -1, 100.0, 2.0, 1.0, 240, {"acc_meta": False, "acc_baseline": True})
    flat = [100, 100.3, 99.7, 100]
    idx = pd.date_range(t0, periods=20, freq="15min")
    m15 = pd.DataFrame([flat, [100, 102.5, 99.9, 102]] + [flat] * 18, columns=["open", "high", "low", "close"], index=idx)
    assert sb.resolve(m15, t0 + pd.Timedelta(hours=5)) == 2
    lb = {r["rule"]: r for r in sb.leaderboard()["leaderboard"]}
    assert lb["acc_meta"]["trades"] == 1 and lb["acc_meta"]["ev_per_trade"] > 0
    assert lb["acc_baseline"]["trades"] == 2


# ---------------- Adversarial market testing
def test_engine_is_safe_in_every_hostile_scenario(demo):
    eng = DecisionEngine(Store())
    as_of = (pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=3)).to_pydatetime()
    res = ADV.run_all(eng, demo, Mode.DEMO, as_of)
    assert len(res) == len(ADV.SCENARIOS) and all(r["safe"] for r in res)
    hard = {r["scenario"]: r["action"] for r in res}
    for sc in ("stale_feed", "clock_skew_future", "source_conflict", "frozen_feed", "bad_tick", "feed_gap", "flash_crash_quote"):
        assert hard[sc] == "UNAVAILABLE", sc


# ---------------- Research integrity
def test_deflated_sharpe_penalises_many_trials():
    rng = np.random.default_rng(0)
    r = rng.normal(0.08, 1.0, 400)
    one, many = INT.deflated_sharpe(r, 1), INT.deflated_sharpe(r, 500)
    assert many["deflated_sharpe_prob"] < one["deflated_sharpe_prob"]
    assert many["expected_max_sharpe_by_luck"] > 0
    assert not INT.deflated_sharpe(rng.normal(0, 1, 400), 100)["significant"]


def test_experiment_ledger_counts_distinct_trials(tmp_path):
    led = INT.ExperimentLedger(tmp_path / "e.jsonl")
    led.log("backtest", {"a": 1}, "ds1", {})
    led.log("backtest", {"a": 1}, "ds1", {})
    led.log("backtest", {"a": 2}, "ds1", {})
    assert len(led.entries()) == 3 and led.trials("backtest") == 2


def test_preregistration_detects_changes(tmp_path):
    p = tmp_path / "prereg.json"
    INT.preregister(p, {"min_edge": 0.1})
    assert INT.check_preregistration(p, {"min_edge": 0.1}, True) == []
    msg = INT.check_preregistration(p, {"min_edge": 0.05}, True)
    assert msg and "متحيزة" in msg[0]


# ---------------- API
def test_v4_endpoints():
    c = TestClient(create_app(":memory:"))
    adv = c.get("/research/adversarial").json()
    assert adv["all_safe"]
    assert c.get("/shadow").json()["resolved"] == 0
    assert "active" in c.get("/governance").json()
    bt = c.get("/research/backtest").json()
    assert "realistic_execution" in bt and "integrity" in bt and "trade_pnls" not in bt
