"""Research Integrity Engine (V4 #10).

* Experiment ledger: every research run is appended (config hash, dataset fingerprint, metrics) so the number
  of trials behind any reported result is known.
* Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014): probability that the best Sharpe among N trials is
  genuinely > 0 after selection bias, non-normal returns and sample length.
* Pre-registration: a frozen configuration hash; changing it after the holdout was used is flagged.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

EULER = 0.5772156649


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16]


def dataset_fingerprint(df) -> str:
    h = hashlib.sha256()
    h.update(str(len(df)).encode())
    if len(df):
        h.update(str(df.index[0]).encode() + str(df.index[-1]).encode())
        h.update(np.round(df["close"].to_numpy()[:: max(1, len(df) // 500)], 4).tobytes())
    return h.hexdigest()[:16]


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    if n_trials <= 1:
        return 0.0
    z1 = stats.norm.ppf(1 - 1 / n_trials)
    z2 = stats.norm.ppf(1 - 1 / (n_trials * np.e))
    return float(np.sqrt(var_sr) * ((1 - EULER) * z1 + EULER * z2))


def probabilistic_sharpe(returns: np.ndarray, sr_benchmark: float = 0.0) -> float:
    r = np.asarray(returns, float)
    n = len(r)
    if n < 10 or r.std(ddof=1) == 0:
        return float("nan")
    sr = r.mean() / r.std(ddof=1)
    g3, g4 = stats.skew(r), stats.kurtosis(r, fisher=False)
    den = np.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return float(stats.norm.cdf((sr - sr_benchmark) * np.sqrt(n - 1) / den))


def deflated_sharpe(returns: np.ndarray, n_trials: int, trial_sr_var: float | None = None) -> dict:
    r = np.asarray(returns, float)
    sr = float(r.mean() / r.std(ddof=1)) if len(r) > 1 and r.std(ddof=1) > 0 else float("nan")
    var = trial_sr_var if trial_sr_var is not None else (1.0 / max(len(r) - 1, 1))
    sr0 = expected_max_sharpe(n_trials, var)
    dsr = probabilistic_sharpe(r, sr0)
    return {"per_trade_sharpe": None if sr != sr else round(sr, 4), "trials": n_trials,
            "expected_max_sharpe_by_luck": round(sr0, 4), "deflated_sharpe_prob": None if dsr != dsr else round(dsr, 4),
            "significant": bool(dsr == dsr and dsr >= 0.95)}


class ExperimentLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def log(self, kind: str, cfg: dict, dataset_fp: str, metrics: dict) -> dict:
        rec = {"at": datetime.now(timezone.utc).isoformat(), "kind": kind, "config_hash": config_hash(cfg),
               "dataset": dataset_fp, "metrics": metrics}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return rec

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def trials(self, kind: str | None = None) -> int:
        return len({(e["kind"], e["config_hash"], e["dataset"]) for e in self.entries() if kind in (None, e["kind"])})


def preregister(path: str | Path, cfg: dict) -> str:
    p = Path(path)
    h = config_hash(cfg)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"registered_at": datetime.now(timezone.utc).isoformat(), "config_hash": h,
                                 "config": cfg}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return h


def check_preregistration(path: str | Path, cfg: dict, holdout_used: bool) -> list[str]:
    p = Path(path)
    if not p.exists():
        return ["لا يوجد تسجيل مسبق للإعدادات"]
    reg = json.loads(p.read_text(encoding="utf-8"))
    if reg["config_hash"] != config_hash(cfg):
        return ["تغيّرت الإعدادات بعد التسجيل المسبق" + (" وبعد استخدام فترة الاختبار النهائية — النتائج متحيزة" if holdout_used else "")]
    return []
