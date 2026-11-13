"""SQLite audit log for decisions and the exact input snapshots needed to replay them."""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import threading
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS decisions (
  decision_id TEXT PRIMARY KEY,
  analyzed_at_utc TEXT NOT NULL,
  mode TEXT NOT NULL,
  action TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  decision_id TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  record_hash TEXT NOT NULL,
  record TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_hash TEXT PRIMARY KEY,
  created_at_utc TEXT NOT NULL,
  data BLOB NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.executescript(DDL)

    def save_snapshot(self, snapshot_hash: str, created_at: str, data: dict) -> None:
        blob = gzip.compress(json.dumps(data, sort_keys=True).encode())
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO snapshots VALUES (?,?,?)", (snapshot_hash, created_at, blob))
            self._conn.commit()

    def load_snapshot(self, snapshot_hash: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM snapshots WHERE snapshot_hash=?", (snapshot_hash,)).fetchone()
        return json.loads(gzip.decompress(row[0])) if row else None

    def save_decision(self, d) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?,?)",
                               (d.decision_id, d.analyzed_at_utc.isoformat(), d.mode.value, d.action.value,
                                d.snapshot_hash, d.model_dump_json()))
            self._conn.commit()

    # ---------------- Decision Audit Trail (V4 #4): append-only, hash-chained
    GENESIS = "0" * 64

    def append_audit(self, decision_id: str, created_at: str, record: dict) -> str:
        body = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
        with self._lock:
            row = self._conn.execute("SELECT record_hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row[0] if row else self.GENESIS
            h = hashlib.sha256((prev + body).encode()).hexdigest()
            self._conn.execute("INSERT INTO audit (decision_id, created_at_utc, prev_hash, record_hash, record) "
                               "VALUES (?,?,?,?,?)", (decision_id, created_at, prev, h, body))
            self._conn.commit()
        return h

    def audit_record(self, decision_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT seq, prev_hash, record_hash, record FROM audit WHERE decision_id=? "
                                     "ORDER BY seq DESC LIMIT 1", (decision_id,)).fetchone()
        if not row:
            return None
        return {"seq": row[0], "prev_hash": row[1], "record_hash": row[2], "record": json.loads(row[3])}

    def verify_audit(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT seq, prev_hash, record_hash, record FROM audit ORDER BY seq").fetchall()
        prev = self.GENESIS
        for seq, p, h, body in rows:
            if p != prev or hashlib.sha256((prev + body).encode()).hexdigest() != h:
                return {"valid": False, "broken_at_seq": seq, "records": len(rows)}
            prev = h
        return {"valid": True, "records": len(rows), "head": prev}

    def history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM decisions ORDER BY analyzed_at_utc DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def last_by_signature(self, action: str, mode: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM decisions WHERE action=? AND mode=? ORDER BY analyzed_at_utc DESC LIMIT 1",
                (action, mode)).fetchone()
        return json.loads(row[0]) if row else None
