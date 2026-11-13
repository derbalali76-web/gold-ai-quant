from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from goldquant import backtest as BT
from goldquant import path as P
from goldquant.api import Settings, create_app
from goldquant.context import MarketContext
from goldquant.engine import DecisionEngine, PathService
from goldquant.intel import analog as AN
from goldquant.intel import counterfactual as CF
from goldquant.intel import divergence as DIV
from goldquant.intel import expectation as EX
from goldquant.intel import info_value as IV
from goldquant.intel import liquidity_trap as LT
from goldquant.intel import micro_edge as ME
from goldquant.paper import PaperLedger
from goldquant.schemas import Action, Mode
from goldquant.store import Store


def bars(rows, start="2026-01-05 08:00"):
    idx = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


# ---------------- C: liquidity trap
def test_sweep_low_reclaim_detected():
    rows = [[100, 101, 99, 100]] * 40 + [[100, 100.5, 97.0, 100.2]]
    ev = LT.scan(bars(rows))
    assert any(e.kind == "SWEEP_LOW_RECLAIM" and e.implied_sign == 1 for e in ev)


def test_failed_breakout_up_detected():
    rows = [[100, 101, 99, 100]] * 40 + [[100, 102.5, 100, 102.0], [102, 102.2, 99.5, 100.0]]
    ev = LT.scan(bars(rows))
    assert any(e.kind == "FAILED_BREAKOUT_UP" for e in ev)


def test_quiet_market_no_trap():
    rng = np.random.default_rng(0)
    c = 100 + np.cumsum(rng.normal(0, 0.01, 60))
    rows = [[x, x + 0.5, x - 0.5, x] for x in c]
    assert not [e for e in LT.scan(bars(rows)) if e.kind != "WICK_ANOMALY"]


# ---------------- C: divergence / Granger
def test_divergence_flags_decoupling():
    rng = np.random.default_rng(1)
    n = 200
    silver_r = rng.normal(0, 0.01, n)
    gold_r = 0.8 * silver_r + rng.normal(0, 0.002, n)
    gold_r[-10:] += 0.01  # gold rallies alone
    idx = pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC")
    g, s = pd.Series(100 * np.exp(np.cumsum(gold_r)), idx), pd.Series(20 * np.exp(np.cumsum(silver_r)), idx)
    out = DIV.divergence(g, {"silver": s})
    assert out["abnormal"] and out["z_residual"] > 2 and 0.6 < out["betas"]["silver"] < 1.0


def test_granger_detects_lead_and_not_noise():
    rng = np.random.default_rng(2)
    x = rng.normal(size=600)
    y = np.r_[0, 0.6 * x[:-1]] + rng.normal(scale=0.5, size=600)
    lead = DIV.granger(pd.Series(y), pd.Series(x), 2)
    noise = DIV.granger(pd.Series(rng.normal(size=600)), pd.Series(rng.normal(size=600)), 2)
    assert lead["p"] < 1e-6 and noise["p"] > 0.01
    st = DIV.granger_stability(pd.Series(y), pd.Series(x), 2)
    assert st["share_significant"] == 1.0 and "ليست سببية" in st["label_ar"]


# ---------------- C: expectation gap / priced-in / missing reaction
def test_expectation_engines_disabled_without_data():
    assert EX.standardized_surprise(None, 0.3, [0.1] * 10) is None
    assert EX.standardized_surprise(0.5, 0.3, [0.1, 0.2]) is None  # too little history to scale
    assert EX.reaction_beta([], bars([[1, 1, 1, 1]] * 5)) is None
    assert EX.priced_in(bars([[1, 1, 1, 1]] * 5), "2026-01-05T09:00Z", 1.0, None) is None


def test_expectation_reaction_and_missing_reaction():
    rng = np.random.default_rng(3)
    n = 96 * 40
    idx = pd.date_range("2025-06-02", periods=n, freq="15min", tz="UTC")
    close = np.full(n, 2000.0)
    events = []
    for k in range(12):
        t = idx[96 * (k + 2) + 54]  # 13:30
        z = float(rng.choice([-1.5, -1, 1, 1.5]))
        pos = idx.get_loc(t)
        close[pos:] += -8 * z  # hawkish surprise -> gold down
        events.append({"time_utc": str(t), "surprise_z": z})
    m15 = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5, "close": close}, index=idx)
    beta = EX.reaction_beta(events, m15)
    assert beta["beta"] < 0 and beta["n"] >= 8
    t_new = idx[96 * 30 + 54]
    mr = EX.missing_reaction(m15, t_new, 1.5, {"beta": beta["beta"], "resid_sd": 0.0005}, t_new + pd.Timedelta(hours=1))
    assert mr["missing_reaction"]  # no move after a big surprise


def test_surprise_scaling():
    assert EX.standardized_surprise(0.5, 0.3, [0.1, -0.1, 0.2, -0.2, 0.0, 0.1, -0.1, 0.05]) == pytest.approx(
        0.2 / np.std([0.1, -0.1, 0.2, -0.2, 0.0, 0.1, -0.1, 0.05], ddof=1))


# ---------------- D: analogs / counterfactual
@pytest.fixture(scope="module")
def ds(demo_bars):
    return P.build_path_dataset(demo_bars["M15"], demo_bars["H1"], demo_bars["H4"])


def test_analogs_use_only_known_past(ds):
    as_of = ds["decision_time"].iloc[len(ds) * 2 // 3]
    q = ds[ds["decision_time"] == as_of].iloc[0]
    a = AN.analogs(ds, q, 1, as_of)
    assert a and a["k"] == 50 and abs(sum(a["neighbours"].values()) - 1) < 1e-6
    assert all(pd.Timestamp(d).date() <= (as_of - pd.Timedelta(days=2)).date() for d in a["dates"])


def test_counterfactual_fill_monotone(demo_bars):
    fe = CF.forward_extremes(demo_bars["M15"])
    as_of = fe.index[-100]
    near = CF.compare(fe, 1, 0.25, 2.0, as_of)
    far = CF.compare(fe, 1, 2.0, 2.0, as_of)
    assert near["fill_probability"] > far["fill_probability"] > 0
    assert (fe["known_at"] > fe.index).all()


# ---------------- E: micro-edge / info value
def test_bh_procedure():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216])
    assert ME.benjamini_hochberg(p, 0.05).sum() == 2


def test_micro_edge_controls_false_discoveries(ds):
    r = ME.discover(ds)
    assert r["tested"] > 50
    for c in r["confirmed"]:
        assert c["conf_p"] < 0.05 and c["conf_n"] >= 30


def test_micro_edge_pure_noise_finds_nothing():
    rng = np.random.default_rng(5)
    n = 20000
    t = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    d = pd.DataFrame({f: rng.normal(size=n) for f in ME.CANDIDATES})
    d["session"] = rng.choice(["ASIA", "LONDON", "NEW_YORK"], n)
    d["dir"] = rng.choice([-1.0, 1.0], n)
    d["out_240"] = rng.choice([1.0, -1.0, 0.0], n)
    d["decision_time"] = t
    d["known_240"] = t + pd.Timedelta(minutes=240)
    assert ME.discover(d)["confirmed"] == []


def test_information_value_restores_features(ds):
    from goldquant import model as M
    before = list(M.FEATURES)
    r = IV.ablation(ds.iloc[: len(ds) // 2])
    assert M.FEATURES == before and set(r["groups"]) == set(IV.GROUPS)


# ---------------- F: backtest + paper
def test_backtest_runs_with_costs_and_baseline(demo_bars):
    r = BT.run(demo_bars["M15"], demo_bars["H1"], demo_bars["H4"])
    assert r["period"] == "DEVELOPMENT" and 0 <= r["abstention_rate"] <= 1
    assert r["baseline"]["trades"] >= r["trades"]
    for t in r["trades_sample"]:
        assert t["outcome"] in (-1, 0, 1)
        if t["outcome"] == 1:
            assert t["pnl"] < t["risk"]  # costs make a 1R win smaller than 1R
    if r["trades"] < 300:
        assert r["warnings"]


def test_backtest_final_holdout_is_logged(demo_bars, tmp_path):
    reg = tmp_path / "holdout.json"
    BT.run(demo_bars["M15"], demo_bars["H1"], demo_bars["H4"], final=True, registry=reg)
    r = BT.run(demo_bars["M15"], demo_bars["H1"], demo_bars["H4"], final=True, registry=reg)
    assert any("استُخدمت 2" in w for w in r["warnings"])


class _D:  # minimal decision stand-in for the ledger
    def __init__(self, did, action, t, entry=(99.9, 100.1), sl=98.0, tp=102.0):
        from goldquant.schemas import Action as A
        self.decision_id, self.action = did, A(action)
        self.mode = Mode.LIVE
        self.analyzed_at_utc, self.valid_until_utc = t, t + timedelta(minutes=15)
        self.entry_min, self.entry_max, self.stop_loss, self.tp1 = entry[0], entry[1], sl, tp
        self.horizon_minutes = 240
        self.probability_target_before_stop, self.probability_stop_before_target = 0.5, 0.4


def test_paper_ledger_fill_tp_sl_and_not_filled():
    t0 = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    flat = [100, 100.2, 99.8, 100]
    led = PaperLedger()
    led.record(_D("win", "BUY", t0))
    led.record(_D("nofill", "BUY", t0, entry=(90, 90.5), sl=88, tp=92))
    led.record(_D("loss", "SELL", t0, sl=101.5, tp=98.5))
    led.record(_D("wait", "WAIT", t0))
    m15 = bars([flat, [100, 102.5, 99.9, 102]] + [flat] * 20, start="2026-01-05 10:00")
    n = led.resolve(m15, t0 + timedelta(hours=5))
    s = led.stats()
    assert n == 3 and s["recorded"] == 3 and s["not_filled"] == 1 and s["closed"] == 2 and s["win_rate"] == 0.5


# ---------------- engine with context + API extras
def test_context_embargo_and_news_force_wait(demo, monkeypatch):
    from goldquant import anti_trade as AT
    from goldquant import engine as E
    eng = DecisionEngine(Store())
    as_of = (pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=3)).to_pydatetime()
    ctx = MarketContext(calendar_connected=True, embargo_events=["US CPI"],
                        recent_news=[("federalreserve.gov", "FOMC statement", as_of.isoformat())])
    seen = {}
    real = AT.evaluate
    monkeypatch.setattr(E, "anti_trade", lambda c: (seen.setdefault("v", c.critic_vetoes), real(c))[1])
    d = eng.decide(demo, Mode.DEMO, as_of, ctx)
    assert d.action in (Action.WAIT, Action.UNAVAILABLE)
    if d.action == Action.WAIT:
        assert any("CPI" in v for v in seen["v"]) and any("خبر" in v for v in seen["v"])
        assert "news_propagation" in d.engines_used


def test_token_auth(tmp_path):
    st = Settings(tmp_path, "", "s3cret", False, False)
    c = TestClient(create_app(":memory:", settings=st))
    assert c.get("/health").status_code == 200
    assert c.get("/engines").status_code == 401
    assert c.get("/engines", headers={"X-Goldquant-Token": "wrong"}).status_code == 401
    assert c.get("/engines", headers={"X-Goldquant-Token": "s3cret"}).status_code == 200


def test_paper_and_research_endpoints():
    c = TestClient(create_app(":memory:"))
    assert c.get("/paper").json()["stats"]["recorded"] == 0
    g = c.get("/research/granger").json()
    assert g["status"] == "DISABLED"
    me = c.get("/research/micro-edge").json()
    assert "SYNTHETIC" in me["dataset"] and "tested" in me
