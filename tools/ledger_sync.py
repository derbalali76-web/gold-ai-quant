#!/usr/bin/env python3
"""One source of truth for the public ledger's code.

The canonical copy lives in this repository under ledger/; the public ledger repository (ai-quant-ledger) runs a copy.
ledger/MANIFEST.json lists every shared file with its path in the ledger repository and its sha256.

  python tools/ledger_sync.py manifest            rewrite ledger/MANIFEST.json from ledger/
  python tools/ledger_sync.py check               ledger/ matches the manifest (run by the tests)
  python tools/ledger_sync.py diff  LEDGER_DIR    compare a checkout of the ledger repository with the manifest
  python tools/ledger_sync.py push  LEDGER_DIR    copy the canonical files into that checkout (then commit there)

The ledger repository verifies itself against the published manifest every hour (ledger/verify_copy.py).
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ledger"
MANIFEST = SRC / "MANIFEST.json"
# canonical path (under ledger/) -> path inside the ledger repository
FILES = {
    "ledger.py": "ledger.py", "issue.py": "issue.py", "advice.py": "advice.py", "monitor.py": "monitor.py",
    "te_live.py": "te_live.py", "record.sh": "record.sh", "verify_copy.py": "verify_copy.py",
    "README.md": "README.md", "index.html": "index.html", "workflows/record.yml": ".github/workflows/record.yml",
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build() -> dict:
    return {"canonical": "derbalali76-web/gold-ai-quant:ledger/", "files": {dst: sha(SRC / src) for src, dst in sorted(FILES.items())}}


def check() -> list[str]:
    if not MANIFEST.exists():
        return ["ledger/MANIFEST.json missing"]
    want = json.loads(MANIFEST.read_text())["files"]
    have = build()["files"]
    errs = [f"{k}: canonical file changed but manifest not updated" for k in have if want.get(k) != have[k]]
    errs += [f"{k}: in manifest but not shared" for k in want if k not in have]
    return errs


def diff(ledger_dir: Path) -> list[str]:
    want = json.loads(MANIFEST.read_text())["files"]
    out = []
    for dst, h in want.items():
        p = ledger_dir / dst
        if not p.exists():
            out.append(f"{dst}: missing in the ledger repository")
        elif sha(p) != h:
            out.append(f"{dst}: differs from the canonical copy")
    return out


def push(ledger_dir: Path) -> list[str]:
    done = []
    for src, dst in FILES.items():
        p = ledger_dir / dst
        if not p.exists() or sha(p) != sha(SRC / src):
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SRC / src, p)
            done.append(dst)
    shutil.copy2(MANIFEST, ledger_dir / "MANIFEST.json")
    return done


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "manifest":
        MANIFEST.write_text(json.dumps(build(), indent=1) + "\n")
        print("manifest written:", len(FILES), "files")
        return 0
    if cmd == "check":
        e = check()
        print("\n".join(e) or "ledger copy: manifest ok")
        return 1 if e else 0
    if cmd in ("diff", "push") and len(argv) > 2:
        r = diff(Path(argv[2])) if cmd == "diff" else push(Path(argv[2]))
        print("\n".join(r) or ("no drift" if cmd == "diff" else "nothing to copy"))
        return 1 if (cmd == "diff" and r) else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
