import json

import numpy as np
import pandas as pd
import pytest

from goldquant import path as P
from goldquant.precision import barrier as BR
from goldquant.precision import calibration as CAL
from goldquant.precision import data as D
from goldquant.precision import production as PRD
from goldquant.precision import promotion as PR
from goldquant.precision import robustness as RB
from goldquant.precision import wf as W
from goldquant.regime import classify, volatility_regime
from goldquant.features import frame_features


# ---------------- calibration
def test_isotonic_fixes_overconfidence():
    rng = np.random.default_rng(0)
    true = rng.uniform(0.2, 0.8, 6000)
    y = (rng.uniform(size=6000) < true).astype(float)
    raw = np.clip(0.5 + 1.8 * (true - 0.5), 0.01, 0.99)  # overconfident
    cal = CAL.Calibrator().fit(raw[:3000], y[:3000])
    assert CAL.ece(cal.transform(raw[3000:]), y[3000:]) < CAL.ece(raw[3000:], y[3000:]) / 2
    assert cal.method_used == "isotonic"
    assert CAL.Calibrator().fit(raw[:500], y[:500]).method_used == "platt"


def test_calibration_verdict_rules():
    passes = 0
    for seed in range(40):  # perfectly calibrated data passes ~95 % of the time (5 % type-I error)
        rng = np.random.default_rng(seed)
        p = rng.uniform(0.1, 0.9, 5000)
        passes += CAL.verdict(p, (rng.uniform(size=5000) < p).astype(float)).passed
    assert passes >= 34
    rng = np.random.default_rng(1)
    p = rng.uniform(0.1, 0.9, 5000)
    y = (rng.uniform(size=5000) < p).astype(float)
    assert not CAL.verdict(np.clip(p + 0.15, 0, 1), y).passed  # biased
    assert not CAL.verdict(p[:100], y[:100]).passed  # too few samples


def test_spiegelhalter_and_decomposition():
    rng = np.random.default_rng(2)
    p = rng.uniform(0.1, 0.9, 4000)
    y = (rng.uniform(size=4000) < p).astype(float)
    z, pv = CAL.spiegelhalter(p, y)
    assert pv > 0.01
    d = CAL.brier_decomposition(p, y)
    assert d["brier"] == pytest.approx(d["reliability"] - d["resolution"] + d["uncertainty"], abs=0.01)


def test_three_class_calibration_is_simplex():
    rng = np.random.default_rng(3)
    p = rng.dirichlet([2, 2, 1], 2000)
    y = np.array([rng.choice([1, -1, 0], p=pi) for pi in p])
    out = CAL.calibrate_three_class(p[:1000], y[:1000], p[1000:])
    assert np.allclose(out.sum(axis=1), 1) and (out >= 0).all()


# ---------------- signal dataset
@pytest.fixture(scope="module")
def sets(demo_bars):
    m15, h1, h4 = demo_bars["M15"], demo_bars["H1"], demo_bars["H4"]
    return D.build_signal_dataset(m15, h1, h4), P.build_path_dataset(m15, h1, h4)


def test_signal_dataset_pnl_includes_costs(sets):
    S, _ = sets
    tp = S[S["out"] == 1]
    risk = S.loc[tp.index, "atr"] * 2.0
    assert (tp["pnl"] < risk + 1e-9).all()  # costs/adverse fill make a 1R win < 1R
    assert ((S["known_at"] - S["decision_time"]) <= pd.Timedelta(minutes=240)).all()
    assert (S["known_at"] > S["decision_time"]).all()


def test_signal_outcomes_match_path_dataset(sets):
    S, ds = sets
    j = ds.set_index(["decision_time", "dir"])["out_240"]
    m = j.reindex(pd.MultiIndex.from_arrays([S["decision_time"], S["dir"]]))
    agree = (m.to_numpy() == S["out"].to_numpy()).mean()
    assert agree > 0.99


def test_vectorized_regime_matches_classify(demo_bars):
    f15 = frame_features(demo_bars["M15"])
    vec = D.vectorized_vol_regime(f15)
    for i in (2000, 4000, 6000, 8000):
        r = classify(f15.iloc[: i + 1].tail(501))
        z = f15["ret_z"].iloc[i]
        assert vec.iloc[i] == volatility_regime(r, 0.0 if z != z else float(z))


# ---------------- walk-forward: leakage guards
@pytest.fixture(scope="module")
def wf(sets):
    S, ds = sets
    return W.run(S, ds, keep_models=True)


def test_windows_are_ordered_with_embargo(wf):
    emb = pd.Timedelta(minutes=240)
    for f in wf["folds"]:
        tr_end, (c0, c1), (t0, t1) = pd.Timestamp(f.train_end), map(pd.Timestamp, f.cal), map(pd.Timestamp, f.test)
        assert tr_end + emb <= c0 < c1 and c1 + emb <= t0 < t1


def test_test_rows_never_in_dev_holdout(wf):
    hold = pd.Timestamp(wf["holdout_start"])
    assert (wf["oos"]["decision_time"] < hold).all()


def test_thresholds_independent_of_test_outcomes(sets):
    """Scrambling TEST-window outcomes must not change any threshold or acceptance decision."""
    S, ds = sets
    S = S.sort_values("decision_time")
    t = S["decision_time"]
    span = t.iloc[-1] - t.iloc[0]
    emb = pd.Timedelta(minutes=240)
    t0 = t.iloc[0] + 0.6 * span
    c1, c0 = t0 - emb, t0 - emb - 0.12 * span
    dsv = W.with_vreg(S, ds)
    b1 = W.fit_bundle(S, dsv, c0 - emb, c0, c1)
    S2, ds2 = S.copy(), dsv.copy()
    fut = S2["decision_time"] >= t0
    S2.loc[fut, "pnl"] = -S2.loc[fut, "pnl"]
    S2.loc[fut, "out"] = -S2.loc[fut, "out"]
    ds2.loc[ds2["decision_time"] >= t0, "out_240"] *= -1
    b2 = W.fit_bundle(S2, ds2, c0 - emb, c0, c1)
    assert b1["tau"] == b2["tau"] and b1["dis_cut"] == b2["dis_cut"]
    test = S[fut].head(300)
    a1, a2 = W.apply_bundle(b1, test), W.apply_bundle(b2, test)
    assert (a1["acc_meta"] == a2["acc_meta"]).all()
    np.testing.assert_allclose(a1["p_tp_cal"], a2["p_tp_cal"])


def test_rule_report_and_frontier(wf):
    oos = wf["oos"]
    rules = W.rule_report(oos)
    assert rules["acc_baseline"]["coverage"] == 1.0
    for v in rules.values():
        if v["accepted"]:
            lo, hi = v["win_rate_ci95"]
            assert lo <= v["win_rate"] <= hi
    fr = W.frontier(oos)
    cov = [f["coverage"] for f in fr]
    assert cov == sorted(cov, reverse=True) and cov[0] == pytest.approx(1.0)
    assert all(not f["precision_95_proven"] or f["win_rate_ci95"][0] >= 0.95 for f in fr)


def test_block_bootstrap_ci():
    x = np.r_[np.ones(200), -np.ones(200)] * 1.0 + 0.5
    days = np.repeat(np.arange(40), 10)
    lo, hi = W.block_bootstrap_mean(x, days)
    assert lo < 0.5 < hi


def test_consensus_report(wf):
    c = W.consensus_report(wf["oos"])
    assert set(c["brier_p_tp_by_model"]) == {"logit", "gradient_boosting", "knn", "moe"}
    assert 0 <= c["all_models_agree_on_ev_sign"] <= 1


# ---------------- robustness / promotion / barrier
def test_robustness_costs_reduce_ev(wf, demo_bars):
    r = RB.stress(wf["oos"], "acc_baseline", demo_bars["M15"], demo_bars["H1"], demo_bars["H4"])
    assert r["cost_x2"] < r["cost_x1.5"] < r["base_ev"]
    assert isinstance(r["passed"], bool)


def test_promotion_gate_requires_everything():
    good_fold = {0: (0.5, 40), 1: (0.4, 40), 2: (0.6, 40), 3: (0.3, 40)}
    base_fold = {k: (0.0, 40) for k in good_fold}
    rules = {"acc_primary_ev": {"per_fold_ev": base_fold},
             "c": {"accepted": 160, "ev_ci95": [0.1, 0.9], "per_fold_ev": good_fold}}
    assert PR.evaluate(rules, "c", {"passed": True})["promoted"]
    assert not PR.evaluate(rules, "c", {"passed": False})["promoted"]
    rules["c"]["ev_ci95"] = [-0.1, 0.9]
    assert not PR.evaluate(rules, "c", {"passed": True})["promoted"]


def test_synthetic_results_never_promote(tmp_path):
    PR.save(tmp_path / "promotions.json", [{"candidate": "acc_meta", "promoted": True}], "SYNTHETIC DEMO")
    assert PR.promoted(tmp_path / "promotions.json") == set()
    PR.save(tmp_path / "promotions.json", [{"candidate": "acc_meta", "promoted": True}], "LIVE HISTORY (TwelveData)")
    assert PR.promoted(tmp_path / "promotions.json") == {"acc_meta"}
    (tmp_path / "precision_report.json").write_text(json.dumps(
        {"dataset": "SYNTHETIC DEMO", "calibration": {"primary_calibrated_p_tp": {"verdict": {"passed": True}}}}))
    assert not PRD.calibration_passed(tmp_path / "precision_report.json")


def test_dynamic_barrier_reports_choice_and_default(demo_bars):
    r = BR.optimize(demo_bars["M15"], demo_bars["H1"], demo_bars["H4"], n_folds=3)
    assert r["status"] == "OK"
    for f in r["folds"]:
        assert tuple(f["chosen"]) in BR.GRID
    assert "ev" in r["dynamic"] and "ev" in r["default"]


def test_production_service_scores_current_bar(demo, demo_bars, sets, tmp_path):
    _, ds = sets
    svc = PRD.PrecisionService(tmp_path)
    as_of = demo.default_as_of()
    out = svc.evaluate_now(demo_bars, ds, as_of, 1)
    assert out is None or (abs(out["p_tp_cal"] + out["p_sl_cal"] + out["p_none_cal"] - 1) < 1e-6
                           and set(out["accept"]) == set(W.RULES))
    assert svc.promoted() == set() and not svc.calibration_ok()
