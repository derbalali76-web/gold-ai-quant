"""forecast-0.1: multi-horizon direction forecasts, online learner, baseline, scoring and verdict."""
import importlib.util
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ledger"))
spec = importlib.util.spec_from_file_location("forecast01", ROOT / "ledger" / "forecast.py")
F = importlib.util.module_from_spec(spec); sys.modules["forecast01"] = F; spec.loader.exec_module(F)

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _series(n, drift=0.0, seed=1):
    rnd = random.Random(seed)
    p, out = 100.0, []
    for i in range(n):
        o = p
        p = p * math.exp(drift + rnd.gauss(0, 0.004))
        t = (T0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append([t, o, max(o, p) * 1.001, min(o, p) * 0.999, p])
    return out


def _write(repo, n, drift=0.0):
    for k, a in enumerate(F.ASSETS):
        (repo / F.BARS[a]).write_text(json.dumps(_series(n, drift, seed=k + 1)))


def _now(n):  # the clock just after bar n-1 closed
    return T0 + timedelta(hours=n)


def test_features_need_history_and_are_bounded():
    assert F.features([100.0] * 10) is None
    x = F.features([b[4] for b in _series(60)])
    assert len(x) == F.NFEAT and x[-1] == 1.0 and all(abs(v) <= 3.0 for v in x)


def test_learner_moves_toward_outcomes():
    w = [0.0] * F.NFEAT
    x = [1.0, 0.5, 0.0, 0.2, 1.0]
    for _ in range(300):
        w = F.learn(w, x, 1)
    assert F.predict(w, x) > 0.8


def test_first_run_bootstraps_and_records_all_horizons(tmp_path):
    _write(tmp_path, 200)
    st = F.apply(str(tmp_path), _now(200))
    assert st["forecasts"] == len(F.ASSETS) * len(F.HORIZONS)
    lines = F._load(tmp_path / F.FILE)
    assert {e["data"]["h"] for e in lines} == set(F.HORIZONS)
    assert all(0 < e["data"]["p"] < 1 and e["data"]["learned_from"] > 0 for e in lines)
    # running again in the same hour adds nothing
    assert F.apply(str(tmp_path), _now(200))["last_run"]["added"] == 0


def test_stale_bars_record_nothing(tmp_path):
    _write(tmp_path, 100)
    st = F.apply(str(tmp_path), _now(100) + timedelta(hours=5))
    assert st["forecasts"] == 0


def test_outcomes_settle_with_the_right_bar_and_learning_is_out_of_sample(tmp_path):
    n0 = 120
    _write(tmp_path, n0 + 30)
    # the file holds 150 bars but the clock only lets the first 120 be "closed"
    F.apply(str(tmp_path), _now(n0))
    for k in range(1, 30):
        F.apply(str(tmp_path), _now(n0 + k))
    lines = F._load(tmp_path / F.FILE)
    fc = {e["data"]["id"]: e["data"] for e in lines if e["kind"] == "FORECAST"}
    outs = [e for e in lines if e["kind"] == "OUTCOME"]
    assert outs
    bars = {a: {b[0]: b for b in json.loads((tmp_path / F.BARS[a]).read_text())} for a in F.ASSETS}
    for e in outs:
        d = fc[e["data"]["id"]]
        end = (F._ts(d["bar"]) + timedelta(hours=d["h"])).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert e["data"]["y"] == (1 if bars[d["asset"]][end][4] > d["close"] else 0)
        # an outcome is never recorded before the end bar has closed
        assert F._ts(e["recorded_at"]) >= F._ts(end) + timedelta(hours=1)
    # a forecast's training count only includes outcomes settled before it was issued
    for e in lines:
        if e["kind"] == "FORECAST":
            d = e["data"]
            settled_before = sum(1 for o in lines if o["kind"] == "OUTCOME" and o["seq"] < e["seq"]
                                 and fc[o["data"]["id"]]["asset"] == d["asset"] and fc[o["data"]["id"]]["h"] == d["h"])
            assert d["learned_from"] >= settled_before


def test_chain_intact_and_stats_shape(tmp_path):
    _write(tmp_path, 260)
    for k in range(60):
        F.apply(str(tmp_path), _now(200 + k))
    F._load(tmp_path / F.FILE)  # raises if the chain is broken
    st = json.loads((tmp_path / F.STATS).read_text())
    assert set(st["horizons"]) == {"1h", "4h", "24h"}
    assert st["horizons"]["24h"]["verdict"] == "INSUFFICIENT"
    assert st["settled"] > 0


def test_verdict_rules():
    def lines(rows):
        out, seq = [], 0
        for i, (p, pb, y) in enumerate(rows):
            bar = (T0 + timedelta(hours=24 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
            fid = f"BTC|24|{bar}"
            out.append({"kind": "FORECAST", "data": {"id": fid, "asset": "BTC", "h": 24, "bar": bar, "p": p, "p_base": pb}})
            out.append({"kind": "OUTCOME", "data": {"id": fid, "y": y}})
        return out
    good = [(0.8, 0.5, 1) if i % 2 == 0 else (0.2, 0.5, 0) for i in range(120)]
    assert F.stats(lines(good))["horizons"]["24h"]["verdict"] == "USEFUL"
    bad = [(0.2, 0.5, 1) if i % 2 == 0 else (0.8, 0.5, 0) for i in range(120)]
    assert F.stats(lines(bad))["horizons"]["24h"]["verdict"] == "NOT_USEFUL"
    assert F.stats(lines(good[:40]))["horizons"]["24h"]["verdict"] == "INSUFFICIENT"
