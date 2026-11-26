"""beginner-ideas-0.3: ATR gaps / cancel buffer and the bitcoin filter, recorded with a scored shadow."""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ideas03", ROOT / "ledger" / "ideas.py")
I = importlib.util.module_from_spec(spec); sys.modules["ideas03"] = I; spec.loader.exec_module(I)

SUP, RES = [66.0, 68.0], [76.0, 78.0]


def test_same_cases_as_android_filters_test():
    i = I.decide("UP", 70.0, SUP, RES, False, "SOL", None, "DOWN")
    assert i["kind"] == "WAIT_DIP" and i["note"] == "BTC_DOWN" and i["buy_at"] == 68.0
    assert I.decide("UP", 70.0, SUP, RES, False, "BTC", None, "DOWN")["kind"] == "BUY_NOW"
    assert I.decide("UP", 70.0, SUP, RES, False, "SOL", None, "UP")["kind"] == "BUY_NOW"
    assert I.decide("DOWN", 70.0, SUP, RES, True, "SOL")["kind"] == "SELL_REBUY"
    assert I.decide("DOWN", 70.0, SUP, RES, True, "SOL", 2.5)["kind"] == "HOLD_SELL_ABOVE"
    assert abs(I.decide("UP", 70.0, [68.0], RES, False, "SOL", 0.4)["invalid"] - 67.4) < 1e-9


def _snap(asset, price, trend, now):
    return {"price": price, "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": "LIVE", "atr_h1": 0.4,
            "outlooks": [{"horizon": "HOURS", "trend": trend, "supports": SUP, "resistances": RES}]}


def test_shadow_recorded_and_scored(tmp_path):
    now = datetime(2026, 11, 26, 12, 5, tzinfo=timezone.utc)
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "snap_SOL.json").write_text(json.dumps(_snap("SOL", 70.0, "UP", now)))
    (inp / "snap_BTC.json").write_text(json.dumps(_snap("BTC", 90000.0, "DOWN", now)))
    I.apply(str(inp), str(tmp_path), now)
    lines = [json.loads(x) for x in (tmp_path / I.FILE).read_text().splitlines()]
    sol = [e["data"] for e in lines if e["kind"] == "IDEA" and e["data"]["asset"] == "SOL" and e["data"]["mode"] == "cash"][0]
    assert sol["kind"] == "WAIT_DIP" and sol["shadow"]["kind"] == "BUY_NOW" and sol["version"] == "beginner-ideas-0.3"
    # 24 h of bars: price rises to the target without a dip -> the shadow (buy now) wins
    start = now.replace(minute=0) + timedelta(hours=1)
    bars = [[(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"), 70 + h * 0.3, 70.5 + h * 0.3, 69.6 + h * 0.3,
             70.3 + h * 0.3] for h in range(26)]
    (tmp_path / "bars_SOL_H1.json").write_text(json.dumps(bars))
    st = I.apply(str(tmp_path / "empty"), str(tmp_path), now + timedelta(hours=26))
    assert st["btc_filter"]["n"] == 1 and st["btc_filter"]["verdict"] == "INSUFFICIENT"
    assert st["btc_filter"]["shadow_mean_edge_pct"] > st["btc_filter"]["shown_mean_edge_pct"]
    assert "beginner-ideas-0.3" in st["by_version"]
