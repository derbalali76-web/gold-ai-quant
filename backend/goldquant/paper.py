"""Paper-trading ledger: every BUY/SELL is recorded and later resolved against real subsequent bars.

Rules match the backtester: the order fills only if price trades inside the entry range before the signal
expires; then SL/TP are checked bar by bar (same-bar touch => SL); otherwise timeout at the horizon.
Resolved predictions feed live calibration and the drift sentinel.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .model import wilson

DDL = """CREATE TABLE IF NOT EXISTS paper (
 decision_id TEXT PRIMARY KEY, mode TEXT, opened_at TEXT, valid_until TEXT, direction INTEGER,
 entry_min REAL, entry_max REAL, stop REAL, target REAL, horizon_min INTEGER, p_tp REAL, p_sl REAL,
 status TEXT, outcome INTEGER, fill_price REAL, exit_price REAL, resolved_at TEXT, pnl REAL)"""


class PaperLedger:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(self.path, check_same_thread=False)
        self._c.execute(DDL)
        self._lock = threading.Lock()

    def record(self, d) -> None:
        if d.action.value not in ("BUY", "SELL"):
            return
        with self._lock:
            self._c.execute("INSERT OR IGNORE INTO paper VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                d.decision_id, d.mode.value, d.analyzed_at_utc.isoformat(), d.valid_until_utc.isoformat(),
                1 if d.action.value == "BUY" else -1, d.entry_min, d.entry_max, d.stop_loss, d.tp1, d.horizon_minutes,
                d.probability_target_before_stop, d.probability_stop_before_target, "OPEN", None, None, None, None, None))
            self._c.commit()

    def open_trades(self) -> list[dict]:
        with self._lock:
            cur = self._c.execute("SELECT * FROM paper WHERE status='OPEN'")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def resolve(self, m15: pd.DataFrame, as_of: datetime, cost: float = 0.0) -> int:
        """m15: closed M15 bars (index = open time). Returns number of trades resolved."""
        done = 0
        close_t = m15.index + pd.Timedelta(minutes=15)
        for t in self.open_trades():
            opened, valid = pd.Timestamp(t["opened_at"]), pd.Timestamp(t["valid_until"])
            end = opened + pd.Timedelta(minutes=t["horizon_min"])
            if pd.Timestamp(as_of) < min(end, valid):
                continue
            bars = m15[(m15.index >= opened) & (close_t <= end)]
            d = t["direction"]
            fill_i, fill = None, None
            for k, (ts, r) in enumerate(bars.iterrows()):
                if ts >= valid:
                    break
                if r["low"] <= t["entry_max"] and r["high"] >= t["entry_min"]:
                    fill_i, fill = k, (t["entry_max"] if d > 0 else t["entry_min"])  # worst price in range
                    break
            if fill_i is None:
                if pd.Timestamp(as_of) >= valid:
                    self._set(t["decision_id"], "NOT_FILLED", None, None, None, as_of, 0.0)
                    done += 1
                continue
            if pd.Timestamp(as_of) < end:
                continue
            outcome, exit_p = 0, None
            for _, r in bars.iloc[fill_i:].iterrows():
                sl = r["low"] <= t["stop"] if d > 0 else r["high"] >= t["stop"]
                tp = r["high"] >= t["target"] if d > 0 else r["low"] <= t["target"]
                if sl:
                    outcome, exit_p = -1, t["stop"]
                    break
                if tp:
                    outcome, exit_p = 1, t["target"]
                    break
            if exit_p is None:
                exit_p = float(bars["close"].iloc[-1]) if len(bars) else fill
            self._set(t["decision_id"], "CLOSED", outcome, fill, exit_p, as_of, d * (exit_p - fill) - cost)
            done += 1
        return done

    def _set(self, did, status, outcome, fill, exit_p, at, pnl):
        with self._lock:
            self._c.execute("UPDATE paper SET status=?, outcome=?, fill_price=?, exit_price=?, resolved_at=?, pnl=? "
                            "WHERE decision_id=?", (status, outcome, fill, exit_p, pd.Timestamp(at).isoformat(), pnl, did))
            self._c.commit()

    def stats(self) -> dict:
        with self._lock:
            cur = self._c.execute("SELECT mode, status, outcome, pnl, p_tp, p_sl FROM paper")
            rows = cur.fetchall()
        closed = [r for r in rows if r[1] == "CLOSED"]
        n = len(closed)
        wins = sum(1 for r in closed if r[2] == 1)
        ci = wilson(wins, n) if n else None
        br = [float(np.sum((np.array([r[4], r[5], 1 - r[4] - r[5]]) -
                            np.array([r[2] == 1, r[2] == -1, r[2] == 0], dtype=float)) ** 2))
              for r in closed if r[4] is not None and r[5] is not None]
        return {"recorded": len(rows), "open": sum(r[1] == "OPEN" for r in rows),
                "not_filled": sum(r[1] == "NOT_FILLED" for r in rows), "closed": n,
                "win_rate": round(wins / n, 4) if n else None,
                "win_rate_ci95": [round(ci[0], 4), round(ci[1], 4)] if n else None,
                "total_pnl": round(float(sum(r[3] for r in closed)), 2) if n else 0.0,
                "brier_live": round(float(np.mean(br)), 4) if br else None,
                "low_sample_warning": n < 300}


def ledger_state(ledger: "PaperLedger | None", mode: str, now) -> dict:
    """Risk-governor view of the paper ledger for one mode."""
    if ledger is None:
        return {}
    import pandas as _pd
    now_t = _pd.Timestamp(now)
    with ledger._lock:
        rows = ledger._c.execute(
            "SELECT opened_at, status, outcome, pnl, entry_min, entry_max, stop, resolved_at FROM paper WHERE mode=? "
            "ORDER BY opened_at", (mode,)).fetchall()
    day = [r for r in rows if now_t - _pd.Timestamp(r[0]) <= _pd.Timedelta(hours=24)]
    closed = [r for r in rows if r[1] == "CLOSED"]
    pnl_r = 0.0
    for r in closed:
        if r[7] and now_t - _pd.Timestamp(r[7]) <= _pd.Timedelta(hours=24):
            risk = abs((r[4] + r[5]) / 2 - r[6]) or 1.0
            pnl_r += (r[3] or 0.0) / risk
    streak, last_loss = 0, None
    for r in reversed(closed):
        if (r[3] or 0) < 0:
            streak += 1
            last_loss = last_loss or _pd.Timestamp(r[7]).to_pydatetime()
        else:
            break
    return {"signals_24h": len(day), "open_positions": sum(r[1] == "OPEN" for r in rows),
            "pnl_r_24h": round(pnl_r, 3), "consecutive_losses": streak, "last_loss_at": last_loss}
