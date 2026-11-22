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
