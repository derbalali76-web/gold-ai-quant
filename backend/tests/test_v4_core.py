from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from goldquant.api import create_app
from goldquant.engine import DecisionEngine
from goldquant.paper import PaperLedger, ledger_state
from goldquant.providers.base import Bars, Quote
from goldquant.providers.demo import DemoProvider
from goldquant.reliability import court as C
from goldquant.reliability import firewall as FW
from goldquant.reliability import governor as G
from goldquant.reliability.pit import PITLedger
from goldquant.schemas import Action, Evidence, Mode
from goldquant.sources.news import NewsItem
from goldquant.store import Store

NOW = datetime(2026, 1, 7, 14, 0, tzinfo=timezone.utc)


def m15(n=300, start="2026-01-05 00:00", price=2000.0, seed=0):
    rng = np.random.default_rng(seed)
    c = price + np.cumsum(rng.normal(0, 0.5, n))
    idx = pd.date_range(start, periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": c, "high": c + 0.6, "low": c - 0.6, "close": c}, index=idx)


# ---------------- Firewall
def test_firewall_blocks_future_timestamp_jump_and_frozen_feed():
    df = m15()
    as_of = (df.index[-1] + pd.Timedelta(minutes=15)).to_pydatetime()
    ok = Quote(float(df["close"].iloc[-1]) + 0.3, as_of - timedelta(seconds=20), as_of, "x")
    assert FW.check_market(ok, {"M15": df}, as_of, 1.0, True).passed
    fut = Quote(ok.price, as_of + timedelta(minutes=2), as_of, "x")
    assert not FW.check_market(fut, {"M15": df}, as_of, 1.0, True).passed
    jump = Quote(ok.price + 30, ok.observed_at, as_of, "x")
    assert any("قفزة" in b for b in FW.check_market(jump, {"M15": df}, as_of, 1.0, True).blocking)
    frozen = df.copy()
    frozen.iloc[-8:, :] = 2000.0
    assert any("متجمدة" in b for b in FW.check_market(ok, {"M15": frozen}, as_of, 1.0, True).blocking)


def test_firewall_detects_spike_and_stalled_bars():
    df = m15()
    df.iloc[-3, df.columns.get_loc("close")] += 80  # bad tick
    as_of = (df.index[-1] + pd.Timedelta(minutes=15)).to_pydatetime()
    q = Quote(float(df["close"].iloc[-1]), as_of, as_of, "x")
    assert any("شاذة جداً" in b for b in FW.check_market(q, {"M15": df}, as_of, 1.0, True).blocking)
    late = as_of + timedelta(hours=2)
    q2 = Quote(float(df["close"].iloc[-1]), late, late, "x")
    assert any("متأخرة" in b for b in FW.check_market(q2, {"M15": m15()}, late, 1.0, True).blocking)
    assert not any("متأخرة" in b for b in FW.check_market(q2, {"M15": m15()}, late, 1.0, False).blocking)


def test_firewall_quarantines_future_news_and_requires_sources_live():
    good = NewsItem("fed", "a", "", NOW - timedelta(minutes=5), NOW, 1.0)
    bad = NewsItem("x", "b", "", NOW + timedelta(hours=1), NOW, 0.5)
    kept, warns = FW.check_news([good, bad], NOW)
    assert kept == [good] and warns
    assert not FW.check_sources(True, None).passed
    assert FW.check_sources(False, None).passed


# ---------------- PIT
def test_pit_ledger_flags_future_inputs():
    p = PITLedger(NOW)
    p.add("quote", NOW - timedelta(seconds=10))
    p.add("cot", "2026-01-09T20:30:00Z")  # published after the decision
    s = p.summary()
    assert not s["passed"] and s["violations"][0]["input"] == "cot"


def test_engine_pit_summary_recorded_and_clean(demo):
    store = Store()
    eng = DecisionEngine(store)
    d = eng.decide(demo, Mode.DEMO, (pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=3)).to_pydatetime())
    rec = store.audit_record(d.decision_id)["record"]
    assert rec["pit"]["passed"] and rec["pit"]["inputs"] >= 5
    assert rec["versions"]["schema"] == d.schema_version


# ---------------- Risk governor
def _ok_args(**kw):
    a = dict(direction=1, risk_per_oz=4.0, reward_risk=1.0, cost=0.45, atr15=2.0, vol_regime="STRONG_TREND",
             quote_age_s=10, max_quote_age_s=180, ledger_state={}, now=NOW)
    a.update(kw)
    return a


def test_governor_approves_clean_trade():
    assert G.review(**_ok_args()).approved


@pytest.mark.parametrize("bad", [dict(quote_age_s=900), dict(vol_regime="EXCEPTIONAL"), dict(reward_risk=0.5),
                                 dict(risk_per_oz=20.0), dict(risk_per_oz=1.0), dict(cost=2.0),
                                 dict(ledger_state={"signals_24h": 4}), dict(ledger_state={"open_positions": 1}),
                                 dict(ledger_state={"pnl_r_24h": -2.5}),
                                 dict(ledger_state={"consecutive_losses": 3, "last_loss_at": NOW - timedelta(hours=1)})])
def test_governor_vetoes(bad):
    assert not G.review(**_ok_args(**bad)).approved


def test_governor_cooldown_expires():
    st = {"consecutive_losses": 3, "last_loss_at": NOW - timedelta(hours=5)}
    assert G.review(**_ok_args(ledger_state=st)).approved


class _D:
    def __init__(self, did, t, action="BUY"):
        self.decision_id, self.action, self.mode = did, Action(action), Mode.LIVE
        self.analyzed_at_utc, self.valid_until_utc = t, t + timedelta(minutes=15)
        self.entry_min, self.entry_max, self.stop_loss, self.tp1 = 99.9, 100.1, 98.0, 102.0
        self.horizon_minutes = 240
        self.probability_target_before_stop = self.probability_stop_before_target = None


def test_ledger_state_counts_and_losing_streak():
    led = PaperLedger()
    t0 = NOW - timedelta(hours=10)
    for k in range(3):
        led.record(_D(f"l{k}", t0 + timedelta(minutes=k)))
    flat = [100, 100.2, 99.8, 100]
    idx = pd.date_range(t0, periods=30, freq="15min", tz="UTC")
    bars = pd.DataFrame([flat, [100, 100.1, 97.0, 97.5]] + [flat] * 28, columns=["open", "high", "low", "close"], index=idx)
    led.resolve(bars, t0 + timedelta(hours=6))
    st = ledger_state(led, "LIVE", NOW)
    assert st["signals_24h"] == 3 and st["consecutive_losses"] == 3 and st["pnl_r_24h"] < -2.5
    assert not G.review(**_ok_args(ledger_state=st)).approved


# ---------------- Court
def _fw(blocking=()):
    return FW.FirewallResult(blocking=list(blocking))


def test_evidence_judge():
    sup = [Evidence(engine="mtf_bias", weight=0.5, text_ar="a"), Evidence(engine="liquidity_trap", weight=0.3, text_ar="b")]
    con = [Evidence(engine="regime", weight=-0.2, text_ar="c")]
    pit_ok = {"passed": True}
    assert C.evidence_judge(_fw(), pit_ok, sup, con).passed
    assert not C.evidence_judge(_fw(["x"]), pit_ok, sup, con).passed
    assert not C.evidence_judge(_fw(), {"passed": False, "violations": [{"input": "cot"}]}, sup, con).passed
    assert not C.evidence_judge(_fw(), pit_ok, sup[:1], con).passed  # one engine only
    assert not C.evidence_judge(_fw(), pit_ok, sup, con * 5).passed  # contrary outweighs


def test_court_requires_unanimity():
    ok = C.Judgement("a", True)
    no = C.Judgement("b", False, ["x"])
    assert C.rule([ok, ok])[0] and not C.rule([ok, no])[0]


def test_engine_decisions_carry_court_and_wait_by_default(demo):
    eng = DecisionEngine(Store())
    for h in (2, 9, 20):
        d = eng.decide(demo, Mode.DEMO, (pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=h)).to_pydatetime())
        if d.action == Action.WAIT:
            assert {j.judge for j in d.court} == {"statistics", "evidence", "risk_governor"}
            assert not all(j.passed for j in d.court)


def test_spike_in_feed_makes_engine_unavailable(demo):
    class Spiky(DemoProvider):
        def bars(self, tf, as_of, count):
            b = super().bars(tf, as_of, count)
            if tf == "M15":
                df = b.df.copy()
                i = df.columns.get_loc("close")
                df.iloc[-2, i] = df.iloc[-2, i] * 1.05
                df.iloc[-2, df.columns.get_loc("high")] = max(df.iloc[-2]["high"], df.iloc[-2, i])
                b = Bars(tf, df, b.provider, b.fetched_at)
            return b
    d = DecisionEngine(Store()).decide(Spiky(), Mode.DEMO, (pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=3)).to_pydatetime())
    assert d.action == Action.UNAVAILABLE and "جدار" in d.warning_ar


# ---------------- Audit chain
def test_audit_chain_detects_tampering():
    s = Store()
    for k in range(5):
        s.append_audit(f"d{k}", NOW.isoformat(), {"k": k})
    assert s.verify_audit()["valid"]
    s._conn.execute("UPDATE audit SET record=? WHERE seq=3", ('{"k": 99}',))
    v = s.verify_audit()
    assert not v["valid"] and v["broken_at_seq"] == 3


def test_audit_endpoints():
    c = TestClient(create_app(":memory:"))
    d = c.get("/decision").json()
    assert c.get("/audit/verify").json()["valid"]
    r = c.get(f"/audit/{d['decision_id']}").json()
    assert r["record_hash"] == d["audit_hash"]
    assert c.get("/audit/nope").status_code == 404
