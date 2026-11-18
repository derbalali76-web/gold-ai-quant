"""te_live.py (stdlib, runs in the public ledger) must compute exactly what the research code computes."""
import sys
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "ledger"))
import te_live as T  # noqa: E402
from trade_engine import data, rules_v2 as R  # noqa: E402
from trade_engine.sim import Costs, Market, Order, simulate  # noqa: E402

UNTIL = pd.Timestamp("2025-11-15", tz="UTC")


@pytest.fixture(scope="module")
def stores():
    h1 = data.load("BTCUSDT", "1h"); h1 = h1[h1.index < UNTIL]
    q = data.load("BTCUSDT", "15m"); q = q[q.index < UNTIL]
    f = R.features("BTCUSDT", h1, UNTIL)
    fu = R.te_funding("BTCUSDT")
    return h1, q, f, fu


def rows(df, step_ms):
    i = df.index.as_unit("ms").asi8
    return [[int(a), float(o), float(h), float(l), float(c), int(a) + step_ms - 1]
            for a, o, h, l, c in zip(i, df.open, df.high, df.low, df.close)]


def inp_at(h1, fu, t):
    w = h1[(h1.index >= t - pd.Timedelta(hours=2100)) & (h1.index < t)]
    f = fu[(fu.index >= t - pd.Timedelta(days=400)) & (fu.index < t)]
    return {"h1": rows(w, 3600_000), "funding": [[int(k.value // 1_000_000), float(v)] for k, v in f.items()]}


def test_features_and_signal_match_research(stores):
    h1, q, f, fu = stores
    ev = f[(f.t >= pd.Timestamp("2022-06-01", tz="UTC")) & (f.t < pd.Timestamp("2025-11-01", tz="UTC"))]
    sig = R.signal(ev, "H1", 0.10)
    pick = pd.concat([ev[sig].sample(25, random_state=1), ev[~sig].sample(25, random_state=1)])
    for _, r in pick.iterrows():
        t = r.t.to_pydatetime().astimezone(timezone.utc)
        fx = T.features(inp_at(h1, fu, r.t), t)
        assert fx["ok"]
        assert fx["close"] == pytest.approx(r.close, rel=1e-12)
        assert fx["atr"] == pytest.approx(r.atr, rel=1e-6)
        assert fx["r24"] == pytest.approx(r.ret24, abs=1e-12)
        if pd.isna(r.funding_pct):
            assert fx["funding_pct"] is None
        else:
            assert fx["funding_pct"] == pytest.approx(r.funding_pct, abs=1e-12)
        assert T.signal(fx) == bool(R.signal(pd.DataFrame([r]), "H1", 0.10).iloc[0])


def test_resolution_matches_the_research_simulator(stores):
    h1, q, f, fu = stores
    m = Market(q, h1)
    c = Costs.for_asset("BTCUSDT")
    m15 = rows(q[(q.index >= pd.Timestamp("2023-01-01", tz="UTC")) & (q.index < pd.Timestamp("2024-01-01", tz="UTC"))], 900_000)
    rng = np.random.default_rng(3)
    ev = f[(f.t >= pd.Timestamp("2023-01-05", tz="UTC")) & (f.t < pd.Timestamp("2023-12-15", tz="UTC"))]
    now = pd.Timestamp("2024-01-01", tz="UTC").to_pydatetime()
    checked = 0
    for idx in rng.choice(len(ev), 300, replace=False):
        r = ev.iloc[idx]
        t = r.t.to_pydatetime().astimezone(timezone.utc)
        o = T.order_from({"close": r.close, "atr": r.atr}, t)
        ref = simulate(Order(r.t, target=o["target"], stop=o["stop"], limit=o["limit"], entry_bars=3, hold_bars=30), m, c)
        got = T.simulate(o, m15, t, now)
        if ref.outcome == "NOT_FILLED":
            assert got["status"] == "NOT_FILLED"
        else:
            assert got["status"] == ref.outcome and got["entry"] == pytest.approx(ref.entry, abs=0.01)
            assert got["net"] == pytest.approx(ref.net, abs=2e-6)
        checked += 1
    assert checked == 300


def test_chain_scan_order_and_state(tmp_path, stores):
    h1, q, f, fu = stores
    ev = f[(f.t >= pd.Timestamp("2024-01-01", tz="UTC"))]
    t = ev[R.signal(ev, "H1", 0.10)].t.iloc[0]
    inp = inp_at(h1, fu, t)
    inp["m15"] = []
    inp["fetched_at"] = T.iso((t + pd.Timedelta(minutes=20)).to_pydatetime())
    T.START = t.to_pydatetime() - pd.Timedelta(days=1)
    p = tmp_path / "in.json"; p.write_text(__import__("json").dumps(inp))
    assert T.cmd_update(str(p), str(tmp_path)) == 0
    assert T.cmd_update(str(p), str(tmp_path)) == 0          # the same decision is never recorded twice
    lines = T.load_lines(tmp_path)
    assert [l["kind"] for l in lines] == ["SCAN", "ORDER"] and T.verify(tmp_path) == []
    st = __import__("json").loads((tmp_path / "trade_engine" / "state.json").read_text())
    assert st["active"][0]["status"] == "PENDING" and st["record"]["orders"] == 1
