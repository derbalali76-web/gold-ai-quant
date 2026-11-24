"""beginner-ideas-0.1: the ledger copy of the app's rule, recording and scoring."""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ideas", ROOT / "ledger" / "ideas.py")
I = importlib.util.module_from_spec(spec); sys.modules["ideas"] = I; spec.loader.exec_module(I)

SUP, RES = [100.0, 95.0], [120.0, 130.0]


def k(t, p, hold):
    return I.decide(t, p, SUP, RES, hold)["kind"]


def test_rule_matches_android_simpleadvice_cases():
    # the same cases as android SimpleAdviceTest.kt
    assert k("UP", 105.0, False) == "BUY_NOW" and I.decide("UP", 105.0, SUP, RES, False)["invalid"] == 95.0
    assert k("UP", 118.0, False) == "WAIT_DIP"
    assert k("DOWN", 110.0, False) == "WAIT"
    assert k("UP", 105.0, True) == "HOLD_SELL_ABOVE"
    assert k("UP", 118.0, True) == "SELL_REBUY"
    assert k("DOWN", 116.0, True) == "SELL_REBUY"
    assert k("DOWN", 112.0, True) == "HOLD_SELL_ABOVE"  # gold gap 12 < 15 USD (owner rule 2026-11-24)
    assert I.decide("DOWN", 60500.0, [60000.0], [61000.0], True, "BTC")["kind"] == "SELL_REBUY"  # gap 0.83 % >= 0.65 %
    assert I.decide("DOWN", 60300.0, [60000.0], [61000.0], True, "BTC")["kind"] == "HOLD_SELL_ABOVE"  # gap 0.50 %
    assert k("DOWN", 101.0, True) == "HOLD_SELL_ABOVE"
    assert k("UP", None, False) == "NONE" and I.decide("UP", 110.0, [], RES, False)["kind"] == "NONE"


def test_cash_never_sells():
    for t in ("UP", "DOWN", "SIDEWAYS", None):
        for p in (99.0, 101.0, 110.0, 119.0, 125.0):
            assert k(t, p, False) not in ("SELL_REBUY", "HOLD_SELL_ABOVE")


def _snap(now, trend="UP", price=105.0):
    return {"as_of": now.isoformat(), "price": price, "mode": "LIVE", "market_closed": False,
            "outlooks": [{"horizon": "HOURS", "supports": SUP, "resistances": RES, "trend": trend}]}


def test_record_once_per_window_and_score(tmp_path):
    now = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "snap_SOL.json").write_text(json.dumps(_snap(now)))
    st = I.apply(str(inp), str(tmp_path), now)
    assert st["last_run"]["added"] == 2  # cash + holder for SOL HOURS
    st = I.apply(str(inp), str(tmp_path), now + timedelta(hours=1))
    assert st["last_run"]["added"] == 0  # window still open: no second idea
    bars = [[(now + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"), 105, 106, 104, 105] for h in range(24)]
    bars[5] = [bars[5][0], 105, 121, 104, 120]  # target reached
    (tmp_path / "bars_SOL_H1.json").write_text(json.dumps(bars))
    (inp / "snap_SOL.json").unlink()
    st = I.apply(str(inp), str(tmp_path), now + timedelta(hours=26))
    assert st["last_run"]["scored"] == 2
    lines = I._load(tmp_path / I.FILE)
    res = {e["data"]["kind"]: e["data"]["result"] for e in lines if e["kind"] == "IDEA_RESULT"}
    assert res["BUY_NOW"]["exit"] == "TARGET" and res["BUY_NOW"]["success"]
    assert res["HOLD_SELL_ABOVE"]["exit"] == "SOLD_AT_TARGET"


def test_no_trend_field_records_nothing(tmp_path):
    now = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
    s = _snap(now); del s["outlooks"][0]["trend"]
    inp = tmp_path / "in"; inp.mkdir(); (inp / "snap_BTC.json").write_text(json.dumps(s))
    st = I.apply(str(inp), str(tmp_path), now)
    assert st["last_run"]["added"] == 0 and st["last_run"]["trend_in_snapshot"] is False


def test_stale_snapshot_records_nothing(tmp_path):
    now = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
    inp = tmp_path / "in"; inp.mkdir(); (inp / "snap_BTC.json").write_text(json.dumps(_snap(now - timedelta(hours=3))))
    assert I.apply(str(inp), str(tmp_path), now)["last_run"]["added"] == 0


def test_sell_rebuy_flags_rose_no_return():
    d = {"kind": "SELL_REBUY", "price": 118.0, "asset": "BTC", "buy_at": 100.0, "sell_at": 118.0, "invalid": None}
    r = I.score(d, [["t", 118, 125, 117, 124]])
    assert r["exit"] == "NO_REBUY" and r["rose_no_return"] and not r["success"]


def test_chain_tamper_detected(tmp_path):
    now = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
    inp = tmp_path / "in"; inp.mkdir(); (inp / "snap_ETH.json").write_text(json.dumps(_snap(now)))
    I.apply(str(inp), str(tmp_path), now)
    p = tmp_path / I.FILE
    p.write_text(p.read_text().replace('"BUY_NOW"', '"WAIT"', 1))
    try:
        I._load(p); assert False
    except RuntimeError:
        pass
