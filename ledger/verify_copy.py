#!/usr/bin/env python3
"""Runs in the public ledger repository: are the files running here exactly the canonical ones?

Compares every file listed in the canonical manifest (gold-ai-quant ledger/MANIFEST.json, fetched from GitHub)
with the local file. Writes copy_check.json; exit code 0 always (a drift is reported, never blocks recording),
unless --strict is given. If the manifest cannot be fetched the local MANIFEST.json is used and that is said.
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://raw.githubusercontent.com/derbalali76-web/gold-ai-quant/main/ledger/MANIFEST.json"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(repo: Path, manifest: dict, source: str) -> dict:
    drift = []
    for dst, h in manifest.get("files", {}).items():
        p = repo / dst
        if not p.exists():
            drift.append({"file": dst, "problem": "missing"})
        elif sha(p) != h:
            drift.append({"file": dst, "problem": "differs"})
    return {"checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "manifest_source": source,
            "files": len(manifest.get("files", {})), "drift": drift, "ok": not drift}


def main(argv: list[str]) -> int:
    repo = Path(".")
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "ai-quant-ledger"}), timeout=20) as r:
            man, src = json.loads(r.read().decode()), "canonical (gold-ai-quant main)"
    except Exception as e:  # noqa: BLE001
        p = repo / "MANIFEST.json"
        man, src = (json.loads(p.read_text()), f"local copy (canonical unreachable: {type(e).__name__})") if p.exists() else ({}, "none")
    res = run(repo, man, src)
    (repo / "copy_check.json").write_text(json.dumps(res, indent=1) + "\n")
    print("copy check:", "ok" if res["ok"] else f"DRIFT in {len(res['drift'])} file(s)", "-", src)
    return 1 if ("--strict" in argv and not res["ok"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
