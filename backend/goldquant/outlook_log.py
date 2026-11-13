"""Forward (live) log of the WEEK / MONTH outlooks — the only test with zero chance of look-ahead.

The hourly CI job appends one record per (daily bar, horizon) to models/outlook_log.jsonl (committed to the
user's private repository, so it survives restarts of the free server), then resolves records whose holding
period has elapsed and writes models/outlook_track.json. Nothing here feeds back into the rules.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import outlook as OL


def append_today(daily: pd.DataFrame, as_of: datetime, log_path: Path) -> list[dict]:
    """Record the outlook computed from the last CLOSED daily bar (idempotent per bar and horizon)."""
    views = OL.compute(daily, as_of)
    d = daily[daily.index + pd.Timedelta(days=1) <= pd.Timestamp(as_of)]
    if d.empty:
        return []
    bar = d.index[-1]
    existing = {(r["bar"], r["horizon"]) for r in read_log(log_path)}
    new = []
    for v in views:
        if v.action == "UNAVAILABLE" or (bar.isoformat(), v.horizon) in existing:
            continue
        new.append({"bar": bar.isoformat(), "recorded_at": datetime.now(timezone.utc).isoformat(),
                    "horizon": v.horizon, "version": OL.OUTLOOK_VERSION, "action": v.action, "tilt": v.tilt,
                    "validated": v.validated, "close": round(float(d["close"].iloc[-1]), 2)})
    if new:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            for r in new:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return new


def read_log(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(x) for x in log_path.read_text(encoding="utf-8").splitlines() if x.strip()]


def resolve(records: list[dict], daily: pd.DataFrame) -> dict:
    """Outcome of each record after its horizon (trading days counted on the stored daily bars)."""
    idx = {t.isoformat(): i for i, t in enumerate(daily.index)}
    close = daily["close"].to_numpy()
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "horizons": {}, "recent": []}
    for hz, h in OL.HORIZON_DAYS.items():
        rows = [r for r in records if r["horizon"] == hz and r["tilt"] != 0]
        resolved, pending = [], 0
        for r in rows:
            i = idx.get(r["bar"])
            if i is None or i + h >= len(close):
                pending += 1
                continue
            ret = float(np.log(close[i + h] / close[i]))
            resolved.append({**r, "exit_close": round(float(close[i + h]), 2), "return": round(ret, 5),
                             "hit": bool(r["tilt"] * ret - OL.ROUND_TRIP_COST > 0)})
        n = len(resolved)
        hits = sum(x["hit"] for x in resolved)
        validated_only = [x for x in resolved if x["validated"]]
        out["horizons"][hz] = {
            "resolved": n, "hits": hits, "hit_rate": round(hits / n, 4) if n else None, "pending": pending,
            "resolved_validated": len(validated_only),
            "hit_rate_validated": (round(sum(x["hit"] for x in validated_only) / len(validated_only), 4)
                                   if validated_only else None),
            "note_ar": ("سجل أمامي حي: لا يُعتد بالنسبة قبل 30 نتيجة على الأقل" if n < 30 else
                        "سجل أمامي حي بعد التكاليف (تكرار، ليس احتمالاً معايراً)")}
        out["recent"].extend(resolved[-15:])
    out["recent"].sort(key=lambda x: x["bar"], reverse=True)
    return out
