"""Model Governance & Rollback (V4 #8).

Registry (data/model_registry.json) of model versions with their validation metrics and status
(candidate | active | retired | rolled_back). Monitoring compares LIVE paper results with validation:
degradation => automatic rollback to the previous active version, or SAFE_MODE (WAIT-only) if none exists.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SAFE_MODE = "SAFE_MODE"
MIN_RESOLVED = 50
BRIER_TOLERANCE = 0.05


class ModelRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.state = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else \
            {"active": None, "versions": [], "events": []}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def _event(self, kind: str, detail: str):
        self.state["events"].append({"at": datetime.now(timezone.utc).isoformat(), "event": kind, "detail": detail})

    def register(self, version: str, metrics: dict, gate_passed: bool) -> None:
        if any(v["version"] == version for v in self.state["versions"]):
            return
        self.state["versions"].append({"version": version, "metrics": metrics, "gate_passed": gate_passed,
                                       "status": "candidate", "registered_at": datetime.now(timezone.utc).isoformat()})
        self._event("register", version)
        self._save()

    def activate(self, version: str) -> bool:
        v = next((x for x in self.state["versions"] if x["version"] == version), None)
        if v is None or not v["gate_passed"]:
            self._event("activation_refused", f"{version}: gate not passed")
            self._save()
            return False
        prev = self.state["active"]
        if prev and prev != SAFE_MODE:
            next(x for x in self.state["versions"] if x["version"] == prev)["status"] = "retired"
        v["status"], self.state["active"] = "active", version
        self._event("activate", version)
        self._save()
        return True

    @property
    def active(self) -> str | None:
        return self.state["active"]

    @property
    def safe_mode(self) -> bool:
        return self.state["active"] == SAFE_MODE

    def monitor(self, paper_stats: dict, validation_brier: float | None, drift_alarm: bool) -> dict:
        """Returns the action taken: none | rollback | safe_mode."""
        act = self.state["active"]
        if act in (None, SAFE_MODE):
            return {"action": "none", "active": act}
        reasons = []
        n = paper_stats.get("closed", 0)
        if drift_alarm:
            reasons.append("drift alarm")
        if n >= MIN_RESOLVED and validation_brier is not None and paper_stats.get("brier_live") is not None \
                and paper_stats["brier_live"] > validation_brier + BRIER_TOLERANCE:
            reasons.append(f"live Brier {paper_stats['brier_live']} > validation {validation_brier}+{BRIER_TOLERANCE}")
        if n >= MIN_RESOLVED and paper_stats.get("total_pnl", 0) < 0 and (paper_stats.get("win_rate_ci95") or [0, 1])[1] < 0.5:
            reasons.append("paper trading loses with the win-rate CI entirely below 50 %")
        if not reasons:
            return {"action": "none", "active": act}
        cur = next(x for x in self.state["versions"] if x["version"] == act)
        cur["status"] = "rolled_back"
        prev = [x for x in self.state["versions"] if x["status"] == "retired"]
        if prev:
            prev[-1]["status"], self.state["active"] = "active", prev[-1]["version"]
            action = "rollback"
        else:
            self.state["active"] = SAFE_MODE
            action = "safe_mode"
        self._event(action, "; ".join(reasons))
        self._save()
        return {"action": action, "active": self.state["active"], "reasons": reasons}
