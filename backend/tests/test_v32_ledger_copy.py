"""The public ledger's code has one canonical copy (ledger/); the manifest must match it, and the ledger repository's
self-check must detect any drift."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(ROOT / "ledger"))
import ledger_sync as S  # noqa: E402
import verify_copy as V  # noqa: E402


def test_manifest_matches_canonical_files():
    assert S.check() == [], "run: python tools/ledger_sync.py manifest"


def test_push_then_diff_and_self_check_detect_drift(tmp_path):
    S.push(tmp_path)
    assert S.diff(tmp_path) == []
    man = json.loads((tmp_path / "MANIFEST.json").read_text())
    assert V.run(tmp_path, man, "test")["ok"]
    (tmp_path / "record.sh").write_text("echo tampered\n")
    (tmp_path / "issue.py").unlink()
    r = V.run(tmp_path, man, "test")
    assert not r["ok"] and {d["file"] for d in r["drift"]} == {"record.sh", "issue.py"}
    assert set(S.diff(tmp_path)) == {"record.sh: differs from the canonical copy", "issue.py: missing in the ledger repository"}


def test_server_watch_records_restarts_outages_and_memory(tmp_path):
    from datetime import datetime, timedelta, timezone
    import server_watch as W
    t = datetime(2026, 11, 22, 10, tzinfo=timezone.utc)
    h = lambda bid, rss=200.0: {"boot": {"id": bid, "started_at": "x", "uptime_s": 5, "memory_mb": {"rss": rss, "peak": rss}}}
    assert W.observe(tmp_path, h("a"), 1.0, None, t) == ["BOOT"]                     # start of observation
    assert W.observe(tmp_path, h("a"), 1.0, None, t + timedelta(hours=1)) == []       # same process: nothing
    assert W.observe(tmp_path, None, None, "URLError", t + timedelta(hours=2)) == ["DOWN"]
    assert W.observe(tmp_path, None, None, "URLError", t + timedelta(hours=3)) == []  # still down: once
    assert W.observe(tmp_path, h("b", 450.0), 40.0, None, t + timedelta(hours=4)) == ["UP", "BOOT", "MEMORY"]
    s = W.summary(tmp_path, t + timedelta(hours=4))
    assert s["restarts"] == 1 and s["down_events"] == 1 and s["memory_alerts"] == 1 and s["chain_ok"]


def test_health_reports_boot_and_memory():
    from fastapi.testclient import TestClient
    sys.path.insert(0, str(ROOT / "backend"))
    from goldquant.api import create_app
    c = TestClient(create_app(":memory:"))
    a, b = c.get("/health").json(), c.get("/health").json()
    assert a["boot"]["id"] == b["boot"]["id"] and len(a["boot"]["id"]) == 12 and a["boot"]["uptime_s"] >= 0
