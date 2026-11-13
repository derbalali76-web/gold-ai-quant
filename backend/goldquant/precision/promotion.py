"""Promotion gate: no new engine reaches production unless it proves a STABLE improvement over the
production baseline (the current primary EV rule) out-of-sample.

Criteria (all required):
  1. >= 100 accepted OOS trades in total
  2. pooled EV per trade after costs > 0 with the 95 % day-block bootstrap CI entirely above 0
  3. EV better than the baseline rule in >= 75 % of folds (a fold with < 10 trades counts as a failure)
  4. Robustness Engine passed
The decision is written to data/promotions.json; the live engine reads it and ignores anything not promoted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

BASELINE_RULE = "acc_primary_ev"


def evaluate(rules: dict, candidate: str, robustness: dict | None) -> dict:
    c, b = rules[candidate], rules[BASELINE_RULE]
    reasons = []
    if c["accepted"] < 100:
        reasons.append(f"عدد الصفقات خارج العينة {c['accepted']} أقل من 100")
    if not (c["ev_ci95"] and c["ev_ci95"][0] > 0):
        reasons.append("فاصل الثقة للعائد المتوقع بعد التكاليف لا يقع بالكامل فوق الصفر")
    wins, total = 0, 0
    for f, (ev, n) in c["per_fold_ev"].items():
        total += 1
        bev = b["per_fold_ev"].get(f, (None, 0))[0]
        if n >= 10 and (bev is None or ev > bev):
            wins += 1
    folds_all = set(c["per_fold_ev"]) | set(b["per_fold_ev"])
    share = wins / len(folds_all) if folds_all else 0.0
    if share < 0.75:
        reasons.append(f"تفوّق على الأساس في {share:.0%} فقط من الطيّات (المطلوب 75%)")
    if not (robustness and robustness.get("passed")):
        reasons.append("لم يجتز اختبارات المتانة")
    return {"candidate": candidate, "promoted": not reasons, "fold_win_share": round(share, 3), "reasons_ar": reasons}


def save(path: str | Path, decisions: list[dict], dataset_label: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"evaluated_at": datetime.now(timezone.utc).isoformat(), "dataset": dataset_label,
                             "decisions": decisions}, ensure_ascii=False, indent=1), encoding="utf-8")


def promoted(path: str | Path) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    o = json.loads(p.read_text(encoding="utf-8"))
    if not str(o.get("dataset", "")).startswith("LIVE"):
        return set()  # synthetic results can never promote anything to production
    return {d["candidate"] for d in o.get("decisions", []) if d.get("promoted")}
