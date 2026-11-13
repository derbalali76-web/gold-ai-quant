"""Production use of the V3 layer — strictly gated.

* Calibrated probabilities are shown only when the latest precision report was computed on LIVE data and
  its calibration verdict passed; the calibrator itself is refit on the most recent calibration window.
* A selective / meta rule filters live trades only if the promotion gate promoted it on LIVE data.
Synthetic (DEMO) evaluations can never enable either.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .. import model as M
from . import data as D
from . import promotion as PR
from . import wf as W

CAL_WINDOW = pd.Timedelta(days=15)


def calibration_passed(report_path: str | Path) -> bool:
    p = Path(report_path)
    if not p.exists():
        return False
    o = json.loads(p.read_text(encoding="utf-8"))
    if not str(o.get("dataset", "")).startswith("LIVE"):
        return False
    v = o.get("calibration", {}).get("primary_calibrated_p_tp", {}).get("verdict", {})
    return bool(v.get("passed"))


def current_row(table: pd.DataFrame, direction: int) -> pd.DataFrame:
    from ..bias import bias_score
    row = table.iloc[[-1]].copy()
    row["bias_abs"] = np.abs(bias_score(row["h4_slope_ema50_atr"], row["h1_slope_ema50_atr"], row["m30_dist"],
                                        row["ret_16"], row["vr4"]))
    for c in M.DIRECTIONAL:
        row[c] = row[c] * direction
    row["dir"] = float(direction)
    row["decision_time"] = row.index
    return row


class PrecisionService:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self._cache: dict = {}
        self._lock = threading.Lock()

    def promoted(self) -> set[str]:
        return PR.promoted(self.data_dir / "promotions.json")

    def calibration_ok(self) -> bool:
        return calibration_passed(self.data_dir / "precision_report.json")

    def evaluate_now(self, bars: dict, ds: pd.DataFrame, as_of: datetime, direction: int) -> dict | None:
        """Returns calibrated probabilities and the decision of every promoted rule for the current bar."""
        key = as_of.replace(minute=0, second=0, microsecond=0)
        emb = pd.Timedelta(minutes=240)
        with self._lock:
            b = self._cache.get(key)
        table = D.feature_table(bars["M15"], bars["H1"], bars["H4"])
        if b is None:
            S = D.build_signal_dataset(bars["M15"], bars["H1"], bars["H4"], table=table)
            ts = pd.Timestamp(as_of)
            c1 = ts - emb
            c0 = c1 - CAL_WINDOW
            b = W.fit_bundle(S.sort_values("decision_time"), W.with_vreg(S, ds), c0 - emb, c0, c1)
            with self._lock:
                self._cache = {key: b}
        if b is None or direction == 0:
            return None
        row = current_row(table, direction)
        if row[M.FEATURES].isna().any(axis=None):
            return None
        rec = W.apply_bundle(b, row).iloc[0]
        p_cal = (float(rec["p_tp_cal"]), float(rec["p_sl_cal"]))
        return {"p_tp_cal": p_cal[0], "p_sl_cal": p_cal[1], "p_none_cal": max(0.0, 1 - sum(p_cal)),
                "meta_p": None if np.isnan(rec["meta_p"]) else float(rec["meta_p"]),
                "accept": {k: bool(rec[k]) for k in W.RULES}, "n_cal": b["n_cal"],
                "disagreement": float(rec["disagreement"])}
