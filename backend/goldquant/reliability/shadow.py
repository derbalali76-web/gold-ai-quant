"""Shadow Model Tournament (V4 #3): alternative rules are scored on LIVE decisions without ever acting.

Each LIVE bar with a candidate direction records every rule's accept/reject. When the outcome becomes
knowable the hypothetical trade (entry at the decision price + estimated costs, same levels and horizon,
same-bar => stop) is resolved. The leaderboard reports EV after costs with confidence intervals.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from ..model import wilson
from ..risk import EST_SLIPPAGE, EST_SPREAD

DDL = """CREATE TABLE IF NOT EXISTS shadow (
 decision_id TEXT PRIMARY KEY, decision_time TEXT, direction INTEGER, ref_price REAL, stop REAL, target REAL,
 horizon_min INTEGER, accepted TEXT, status TEXT, outcome INTEGER, pnl REAL)"""


class ShadowBook:
    def __init__(self, path: str | Path = ":memory:"):
        self._c = sqlite3.connect(str(path), check_same_thread=False)
        self._c.execute(DDL)
        self._lock = threading.Lock()

    def record(self, decision_id, decision_time, direction, ref_price, risk, tp_r, horizon_min, accepted: dict):
        with self._lock:
            self._c.execute("INSERT OR IGNORE INTO shadow VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                decision_id, pd.Timestamp(decision_time).isoformat(), int(direction), float(ref_price),
                float(ref_price - direction * risk), float(ref_price + direction * tp_r * risk), int(horizon_min),
                json.dumps(accepted), "OPEN", None, None))
            self._c.commit()

    def resolve(self, m15: pd.DataFrame, as_of) -> int:
        with self._lock:
            rows = self._c.execute("SELECT decision_id, decision_time, direction, ref_price, stop, target, horizon_min "
                                   "FROM shadow WHERE status='OPEN'").fetchall()
        done = 0
        close_t = m15.index + pd.Timedelta(minutes=15)
        for did, t, d, ref, stop, target, h in rows:
            t0, end = pd.Timestamp(t), pd.Timestamp(t) + pd.Timedelta(minutes=h)
            if pd.Timestamp(as_of) < end:
                continue
            bars = m15[(m15.index >= t0) & (close_t <= end)]
            entry = ref + d * (EST_SPREAD / 2 + EST_SLIPPAGE)
            outcome, exit_p = 0, None
            for _, b in bars.iterrows():
                sl = b["low"] <= stop if d > 0 else b["high"] >= stop
                tp = b["high"] >= target if d > 0 else b["low"] <= target
                if sl:
                    outcome, exit_p = -1, stop - d * EST_SLIPPAGE
                    break
                if tp:
                    outcome, exit_p = 1, target
                    break
            if exit_p is None:
                exit_p = (float(bars["close"].iloc[-1]) if len(bars) else ref) - d * EST_SPREAD / 2
            with self._lock:
                self._c.execute("UPDATE shadow SET status='CLOSED', outcome=?, pnl=? WHERE decision_id=?",
                                (outcome, d * (exit_p - entry), did))
                self._c.commit()
            done += 1
        return done

    def leaderboard(self) -> dict:
        with self._lock:
            rows = self._c.execute("SELECT accepted, outcome, pnl FROM shadow WHERE status='CLOSED'").fetchall()
        rules: dict = {}
        for acc, outc, pnl in rows:
            for rule, ok in json.loads(acc).items():
                if ok:
                    rules.setdefault(rule, []).append((outc, pnl))
        board = []
        for rule, v in rules.items():
            pnl = np.array([p for _, p in v])
            n, wins = len(pnl), int((pnl > 0).sum())
            lo, hi = wilson(wins, n)
            se = pnl.std(ddof=1) / np.sqrt(n) if n > 1 else float("nan")
            board.append({"rule": rule, "trades": n, "win_rate": round(wins / n, 4),
                          "win_rate_ci95": [round(float(lo), 4), round(float(hi), 4)],
                          "ev_per_trade": round(float(pnl.mean()), 4),
                          "ev_ci95_approx": [round(float(pnl.mean() - 1.96 * se), 4), round(float(pnl.mean() + 1.96 * se), 4)]
                          if n > 1 else None, "low_sample_warning": n < 300})
        board.sort(key=lambda x: x["ev_per_trade"], reverse=True)
        return {"resolved": len(rows), "leaderboard": board,
                "note_ar": "نماذج الظل لا تؤثر على أي قرار؛ ترتيبها وصفي حتى تجتاز بوابة الترقية"}
