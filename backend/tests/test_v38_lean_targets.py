import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("lean", ROOT / "ledger" / "lean.py")
lean = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lean)


def test_statement_targets_nearest_level():
    assert lean.statement("UP", 71.3, [67.2, 65.84], [78.57, 79.68]) == {"direction": "UP", "target": 78.57, "opposite": 67.2}
    assert lean.statement("DOWN", 71.3, [67.2, 65.84], [78.57]) == {"direction": "DOWN", "target": 67.2, "opposite": 78.57}
    assert lean.statement("SIDEWAYS", 71.3, [67.2], [78.57]) is None
    assert lean.statement("UP", 80.0, [67.2], [78.57]) is None


def _bar(t, o, h, l, c):
    return [t.strftime("%Y-%m-%dT%H:%M:%SZ"), o, h, l, c]


def test_record_score_and_daily_sampling(tmp_path):
    now = datetime(2026, 11, 26, 3, 5, tzinfo=timezone.utc)
    snap = {"price": 71.3, "as_of": "2026-11-26T03:00:00Z", "mode": "LIVE",
            "outlooks": [{"horizon": "HOURS", "trend": "UP", "supports": [67.2], "resistances": [78.57]}]}
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "snap_SOL.json").write_text(json.dumps(snap))
    start = datetime(2026, 11, 26, 4, tzinfo=timezone.utc)
    bars = [_bar(start + timedelta(hours=i), 72, 73 + i, 71, 72) for i in range(10)]
    (tmp_path / "bars_SOL_H1.json").write_text(json.dumps(bars))
    st = lean.apply(str(inp), str(tmp_path), now)
    assert st["statements"] == 1 and st["settled"] == 0
    # one hour later: no second sample (24 h rule)
    snap["as_of"] = "2026-11-26T04:00:00Z"; (inp / "snap_SOL.json").write_text(json.dumps(snap))
    st = lean.apply(str(inp), str(tmp_path), now + timedelta(hours=1))
    assert st["statements"] == 1
    # after the bars: high 79 on bar index 6 (closes 11:00) -> reached ~7.9 h after 03:05
    st = lean.apply(str(inp), str(tmp_path), now + timedelta(hours=12))
    assert st["settled"] == 1
    lines = [json.loads(x) for x in (tmp_path / lean.FILE).read_text().splitlines()]
    r = [e for e in lines if e["kind"] == "RESULT"][0]["data"]
    assert r["reached"] and r["in_24h"] and not r["opposite_first"] and 7.5 < r["hours_to_target"] < 8.5
    assert st["by_horizon_direction"]["HOURS|UP"]["verdict"] == "INSUFFICIENT"
