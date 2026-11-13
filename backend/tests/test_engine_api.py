from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from goldquant import critic as critic_mod
from goldquant import engine as engine_mod
from goldquant.api import create_app
from goldquant.engine import DecisionEngine, PathService, PathState
from goldquant.providers.base import Bars
from goldquant.providers.demo import DemoProvider
from goldquant.schemas import Action, Decision, Mode
from goldquant.store import Store


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(":memory:"))


@pytest.fixture(scope="module")
def shared_models():
    return PathService()


def weekday_as_of(demo, hours_back=3):
    t = pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=hours_back)
    return t.to_pydatetime()


# ------------------------------------------------------------------ API
def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "ok" and "disabled" in r["trade_execution"]


def test_decision_contract_and_demo_labels(client):
    r = client.get("/decision", params={"mode": "DEMO"})
    assert r.status_code == 200
    d = Decision(**r.json())
    assert d.mode == Mode.DEMO and d.spot_or_proxy.value == "SYNTHETIC"
    assert d.probability_target_before_stop is None
    assert any("اصطناعية" in m for m in d.missing_data)


def test_demo_replay_is_deterministic(client):
    a = client.get("/decision", params={"demo_step": 4}).json()
    b = client.get("/decision", params={"demo_step": 4}).json()
    ha, hb = a.pop("audit_hash"), b.pop("audit_hash")
    assert a == b and ha != hb  # same decision; the audit chain still records both requests


def test_live_without_provider_is_unavailable(client):
    d = client.get("/decision", params={"mode": "LIVE"}).json()
    assert d["action"] == "UNAVAILABLE" and d["quote"] is None


def test_history_and_metrics(client):
    client.get("/decision", params={"demo_step": 2})
    h = client.get("/history", params={"limit": 5}).json()["decisions"]
    assert 1 <= len(h) <= 5
    m = client.get("/model-metrics").json()
    assert "SYNTHETIC" in m["dataset"] and set(m["horizons"]) == {"15", "30", "60", "240"}


def test_bad_params(client):
    assert client.get("/decision", params={"demo_step": 999}).status_code == 422
    assert client.get("/decision", params={"mode": "REAL"}).status_code == 422


def test_no_execution_endpoints(client):
    paths = {r.path for r in client.app.routes}
    assert not any(k in p.lower() for p in paths for k in ("order", "trade", "execute", "broker"))


# ------------------------------------------------------------------ engine safety
class StaleDemo(DemoProvider):
    def quote(self, as_of):
        q = super().quote(as_of)
        q.observed_at = q.observed_at - timedelta(minutes=30)
        return q


class ShortDemo(DemoProvider):
    def bars(self, timeframe, as_of, count):
        return super().bars(timeframe, as_of, 50)


class CorruptDemo(DemoProvider):
    def bars(self, timeframe, as_of, count):
        b = super().bars(timeframe, as_of, count)
        df = b.df.copy()
        df.iloc[-1, df.columns.get_loc("low")] = df.iloc[-1]["high"] + 5
        return Bars(timeframe, df, b.provider, b.fetched_at)


@pytest.mark.parametrize("prov,needle", [(StaleDemo(), "قديم"), (ShortDemo(), "غير كافية"), (CorruptDemo(), "تالفة")])
def test_bad_data_yields_unavailable(prov, needle, shared_models):
    eng = DecisionEngine(Store(), shared_models)
    d = eng.decide(prov, Mode.DEMO, weekday_as_of(prov))
    assert d.action == Action.UNAVAILABLE and needle in d.warning_ar


def test_weekend_is_unavailable(demo, shared_models):
    eng = DecisionEngine(Store(), shared_models)
    sat = pd.Timestamp("2025-12-27 12:00", tz="UTC").to_pydatetime()
    d = eng.decide(demo, Mode.DEMO, sat)
    assert d.action == Action.UNAVAILABLE


def test_unvalidated_model_never_trades(demo, shared_models):
    eng = DecisionEngine(Store(), shared_models)
    for h in range(0, 60, 6):
        d = eng.decide(demo, Mode.DEMO, weekday_as_of(demo, h))
        if d.action == Action.UNAVAILABLE:
            continue
        st = shared_models.get(demo, d.analyzed_at_utc, {})  # served from cache
        if not st.qualified:
            assert d.action in (Action.WAIT, Action.UNAVAILABLE)


# ------------------------------------------------------------------ trade path with injected qualified path models
class _StubPath:
    def __init__(self, p):
        self.p = np.array(p)
        self.reports = {}

    def predict(self, row):
        return {h: self.p for h in (15, 30, 60, 240)}


class StubPaths(PathService):
    def __init__(self, p=(0.7, 0.2, 0.1), qualified=True):
        super().__init__()
        self.p, self.q = p, qualified

    def get(self, provider, as_of, bars):
        return PathState(_StubPath(self.p), self.q, "stub", None)


def _no_critic(monkeypatch):
    """Isolate the signal path: critic off; evidence & risk judges approve (they are tested separately)."""
    from goldquant.reliability import court as C
    monkeypatch.setattr(engine_mod, "review", lambda *a, **k: critic_mod.CriticResult())
    monkeypatch.setattr(C, "evidence_judge", lambda *a, **k: C.Judgement("evidence", True, []))
    monkeypatch.setattr(C, "risk_judge", lambda *a, **k: C.Judgement("risk_governor", True, []))


def _find_trade(eng, demo, monkeypatch, mode=Mode.DEMO):
    _no_critic(monkeypatch)
    for h in range(0, 400, 3):
        d = eng.decide(demo, mode, weekday_as_of(demo, h))
        if d.action in (Action.BUY, Action.SELL):
            return d
    return None


def test_trade_path_produces_consistent_levels(demo, monkeypatch):
    monkeypatch.setattr(engine_mod, "anti_trade", lambda c: [] if c.direction else ["no dir"])
    eng = DecisionEngine(Store(), StubPaths())
    d = _find_trade(eng, demo, monkeypatch)
    assert d is not None, "expected at least one directional setup in the synthetic timeline"
    Decision(**d.model_dump())
    assert d.horizon_minutes == 240 and d.valid_until_utc > d.analyzed_at_utc
    assert d.probability_target_before_stop is None and not d.probabilities_by_horizon  # DEMO hides all
    assert d.invalidation_ar and d.supporting_evidence and d.reason_short_ar


def test_live_qualified_shows_three_outcome_probabilities(demo, monkeypatch):
    monkeypatch.setattr(engine_mod, "anti_trade", lambda c: [] if c.direction else ["no dir"])
    class _Prec:
        def promoted(self):
            return set()

        def calibration_ok(self):
            return True

        def evaluate_now(self, *a):
            return {"p_tp_cal": 0.6, "p_sl_cal": 0.3, "p_none_cal": 0.1, "meta_p": None, "accept": {}, "n_cal": 500}
    eng = DecisionEngine(Store(), StubPaths((0.6, 0.3, 0.1)), precision=_Prec())
    eng.paths.get = lambda *a: PathState(type("PM", (), {"predict": lambda self, r: {h: np.array([0.6, 0.3, 0.1]) for h in (15, 30, 60, 240)},
                                                       "reports": {240: type("R", (), {"n_oos": 5000, "qualified": True, "brier_model": 0.5, "brier_climatology": 0.6, "max_reliability_gap": 0.02})()}})(),
                                         True, "ok", None)
    d = _find_trade(eng, demo, monkeypatch, mode=Mode.LIVE)
    assert d is not None
    assert d.probability_target_before_stop == pytest.approx(0.6)
    assert d.probability_stop_before_target == pytest.approx(0.3)
    assert d.probability_neither == pytest.approx(0.1)
    assert len(d.probabilities_by_horizon) == 4 and d.calibration_sample_count == 5000
    assert d.expected_net_return is not None


def test_real_anti_trade_blocks_demo_even_with_optimistic_model(demo, monkeypatch):
    """With the REAL anti-trade gate, DEMO data (high data uncertainty) never yields a trade."""
    eng = DecisionEngine(Store(), StubPaths((0.9, 0.05, 0.05)))
    assert _find_trade(eng, demo, monkeypatch) is None


def test_unqualified_model_blocks_trade(demo, monkeypatch):
    eng = DecisionEngine(Store(), StubPaths(qualified=False))
    assert _find_trade(eng, demo, monkeypatch) is None


def test_duplicate_signal_protection(demo, monkeypatch):
    import goldquant.anti_trade as AT
    real = AT.evaluate
    monkeypatch.setattr(engine_mod, "anti_trade",
                        lambda c: [r for r in real(c) if "عدم اليقين" not in r and "نموذج الاحتمالات" not in r
                                   and "العائد المتوقع" not in r])
    eng = DecisionEngine(Store(), StubPaths())
    first = _find_trade(eng, demo, monkeypatch)
    assert first is not None
    again = eng.decide(demo, Mode.DEMO, first.analyzed_at_utc + timedelta(minutes=1))
    reasons = [r for j in again.court for r in j.reasons_ar]
    assert again.action == Action.WAIT and any("تكرار" in r for r in reasons)


def test_live_mode_requires_news_calendar(demo, monkeypatch):
    eng = DecisionEngine(Store(), StubPaths())
    for h in range(0, 200, 6):
        _no_critic(monkeypatch)
        d = eng.decide(DemoProvider(), Mode.LIVE, weekday_as_of(demo, h))
        assert d.action in (Action.WAIT, Action.UNAVAILABLE)


def test_engines_registry_endpoint(client):
    e = client.get("/engines").json()["engines"]
    names = " ".join(x["engine"] for x in e)
    for k in ("Probabilistic Path", "Anti-Trade", "Drift", "Expectation Gap", "Information Value"):
        assert k in names
    assert all(x["status"] in ("ACTIVE", "ACTIVE_BASELINE", "DISABLED_NO_DATA", "PLANNED", "RESEARCH_ONLY") for x in e)


def test_live_without_calibration_pass_hides_numbers(demo, monkeypatch):
    monkeypatch.setattr(engine_mod, "anti_trade", lambda c: [] if c.direction else ["no dir"])
    eng = DecisionEngine(Store(), StubPaths((0.6, 0.3, 0.1)))
    eng.paths.get = lambda *a: PathState(type("PM", (), {"predict": lambda self, r: {h: np.array([0.6, 0.3, 0.1]) for h in (15, 30, 60, 240)},
                                                       "reports": {240: type("R", (), {"n_oos": 5000, "qualified": True, "brier_model": 0.5, "brier_climatology": 0.6, "max_reliability_gap": 0.02})()}})(),
                                         True, "ok", None)
    d = _find_trade(eng, demo, monkeypatch, mode=Mode.LIVE)
    assert d is not None and d.probability_target_before_stop is None and not d.probabilities_by_horizon


def test_promoted_rule_rejection_blocks_trade(demo, monkeypatch):
    import goldquant.anti_trade as AT
    real = AT.evaluate
    monkeypatch.setattr(engine_mod, "anti_trade",
                        lambda c: [r for r in real(c) if "عدم اليقين" not in r and "نموذج الاحتمالات" not in r
                                   and "العائد المتوقع" not in r and "تقويم" not in r])

    class _Prec:
        def promoted(self):
            return {"acc_meta"}

        def calibration_ok(self):
            return False

        def evaluate_now(self, *a):
            return {"p_tp_cal": 0.6, "p_sl_cal": 0.3, "p_none_cal": 0.1, "meta_p": 0.1,
                    "accept": {"acc_meta": False}, "n_cal": 500}
    eng = DecisionEngine(Store(), StubPaths(), precision=_Prec())
    assert _find_trade(eng, demo, monkeypatch, mode=Mode.LIVE) is None
    _Prec.evaluate_now = lambda self, *a: {"p_tp_cal": 0.6, "p_sl_cal": 0.3, "p_none_cal": 0.1, "meta_p": 0.9,
                                           "accept": {"acc_meta": True}, "n_cal": 500}
    assert _find_trade(DecisionEngine(Store(), StubPaths(), precision=_Prec()), demo, monkeypatch, mode=Mode.LIVE) is not None
