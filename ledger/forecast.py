#!/usr/bin/env python3
"""forecast-0.1 — multi-horizon direction forecasts that learn from their own results, scored in public.

PRE-REGISTERED 2026-11-28 (owner request: «يتنبأ بسعر الأصل في فريمات عديدة ثم يتعلم من نفسه»), before any forecast
was recorded. A new version gets a new name; nothing below is changed after results exist.

WHAT IS FORECAST. Every hourly run, for each asset (XAU, BTC, ETH, SOL) and horizon (1 h, 4 h, 24 h): the probability
that the close h hours after the last CLOSED H1 bar is higher than that bar's close. A probability, never a price.
Not recorded when the last closed bar is older than 2 h or fewer than 49 closed bars exist. Ledger lines are
append-only and hash-chained (studies/forecasts.jsonl); nothing is edited later.

THE LEARNER. One online logistic regression per (asset, horizon), 5 inputs: 1 h, 4 h and 24 h return, each divided
by the usual move over that span (48-bar volatility), the RSI(14) distance from 50, and a constant. Plain
stochastic gradient (rate 0.01, L2 0.001). It is updated ONLY with outcomes that were already settled when the
forecast was made, so every forecast is out-of-sample by construction. The weights start from a replay over the
bars the ledger holds when the first run happens (those replayed steps are not forecasts and count for nothing).
The model never changes the app's recommendations; it only changes its own next forecast.

THE BASELINE. The share of rising outcomes seen so far for that (asset, horizon), smoothed (ups + 1) / (n + 2).
It is recorded next to each forecast. Learning is judged only against it.

SCORING. Outcome = the close h hours later vs the issue close (fees ignored: this is a direction forecast).
Brier score of the learner and of the baseline; skill = 1 − Brier_learner / Brier_baseline (> 0 = better than the
baseline). Also accuracy, and a calibration table (forecast bucket → how often it rose).
VERDICT per horizon (all assets pooled), on NON-OVERLAPPING forecasts only (those whose issue hour is a multiple of
h, so a 24 h forecast is counted once a day): d = (p_base − y)² − (p_learner − y)².
  n < 100  → INSUFFICIENT;  else USEFUL when mean(d) > 0 and its t-statistic >= 2.5, otherwise NOT_USEFUL.
Assets are correlated (the three crypto assets move together), so the pooled n overstates independent evidence;
that is why the bar is 2.5, not 2. USEFUL means "worth watching", not a proven edge. Per-asset numbers are shown
but carry no verdict. Standard library only.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ideas import ASSETS, BARS, _append, _load, _ts

VERSION = "forecast-0.1"
HORIZONS = (1, 4, 24)
NFEAT = 5
LR, L2 = 0.01, 0.001
MIN_BARS = 49
STALE = timedelta(hours=2)
MIN_N = 100
T_MIN = 2.5
FILE = Path("studies") / "forecasts.jsonl"
MODEL = Path("studies") / "forecast_model.json"
STATS = Path("studies") / "forecast_stats.json"


# ---------------------------------------------------------------- the learner
def _clip(x: float, k: float = 3.0) -> float:
    return max(-k, min(k, x))


def features(closes: list) -> Optional[list]:
    """Inputs from closed H1 closes (oldest first); None if there is not enough history."""
    if len(closes) < MIN_BARS or min(closes[-MIN_BARS:]) <= 0:
        return None
    c = closes
    rets = [math.log(c[i] / c[i - 1]) for i in range(len(c) - 48, len(c))]
    m = sum(rets) / len(rets)
    vol = max(math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1)), 1e-6)
    gains = [max(c[i] - c[i - 1], 0.0) for i in range(len(c) - 14, len(c))]
    losses = [max(c[i - 1] - c[i], 0.0) for i in range(len(c) - 14, len(c))]
    ag, al = sum(gains) / 14, sum(losses) / 14
    rsi = 100.0 if al == 0 and ag > 0 else 50.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return [_clip(math.log(c[-1] / c[-2]) / vol),
            _clip(math.log(c[-1] / c[-5]) / (vol * 2)),
            _clip(math.log(c[-1] / c[-25]) / (vol * math.sqrt(24))),
            _clip((rsi - 50) / 25),
            1.0]


def predict(w: list, x: list) -> float:
    z = _clip(sum(a * b for a, b in zip(w, x)), 30.0)
    return 1 / (1 + math.exp(-z))


def learn(w: list, x: list, y: int) -> list:
    g = predict(w, x) - y
    return [wi - LR * (g * xi + L2 * wi) for wi, xi in zip(w, x)]


def _fresh() -> dict:
    return {"w": [0.0] * NFEAT, "ups": 0, "n": 0}


def _bars(repo: Path, asset: str) -> list:
    f = repo / BARS[asset]
    try:
        return json.loads(f.read_text()) if f.exists() else []
    except ValueError:
        return []


def _closed(bars: list, now: datetime) -> list:
    return [b for b in bars if _ts(b[0]) + timedelta(hours=1) <= now]


def _hour_index(ts: str) -> int:
    return int(_ts(ts).timestamp() // 3600)


# ---------------------------------------------------------------- record, settle, learn
def _key(a: str, h: int) -> str:
    return f"{a}|{h}"


def bootstrap(model: dict, repo: Path, now: datetime) -> None:
    """First run only: replay the bars on hand in time order (not forecasts, not scored)."""
    for a in ASSETS:
        cl = _closed(_bars(repo, a), now)
        closes = [b[4] for b in cl]
        for h in HORIZONS:
            st = model.setdefault(_key(a, h), _fresh())
            for i in range(MIN_BARS - 1, len(closes) - h):
                x = features(closes[:i + 1])
                if x is None:
                    continue
                y = 1 if closes[i + h] > closes[i] else 0
                st["w"] = learn(st["w"], x, y)
                st["ups"] += y
                st["n"] += 1


def settle(repo: Path, now: datetime, lines: list, model: dict) -> int:
    """Give every forecast whose horizon has passed its outcome and let the learner see it (oldest first)."""
    done = {e["data"]["id"] for e in lines if e["kind"] == "OUTCOME"}
    cache: dict = {}
    n = 0
    for e in [x for x in lines if x["kind"] == "FORECAST" and x["data"]["id"] not in done]:
        d = e["data"]
        a, h = d["asset"], d["h"]
        if a not in cache:
            cache[a] = {b[0]: b for b in _closed(_bars(repo, a), now)}
        end_t = (_ts(d["bar"]) + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = cache[a].get(end_t)
        if end is None:
            continue
        y = 1 if end[4] > d["close"] else 0
        st = model.setdefault(_key(a, h), _fresh())
        st["w"] = learn(st["w"], d["x"], y)
        st["ups"] += y
        st["n"] += 1
        _append(repo / FILE, lines, "OUTCOME", {"id": d["id"], "y": y, "end_close": end[4]}, now)
        n += 1
    return n


def record(repo: Path, now: datetime, lines: list, model: dict) -> int:
    have = {e["data"]["id"] for e in lines if e["kind"] == "FORECAST"}
    added = 0
    for a in ASSETS:
        cl = _closed(_bars(repo, a), now)
        if len(cl) < MIN_BARS or now - (_ts(cl[-1][0]) + timedelta(hours=1)) > STALE:
            continue
        x = features([b[4] for b in cl])
        if x is None:
            continue
        bar = cl[-1][0]
        for h in HORIZONS:
            fid = f"{a}|{h}|{bar}"
            if fid in have:
                continue
            st = model.setdefault(_key(a, h), _fresh())
            data = {"id": fid, "version": VERSION, "asset": a, "h": h, "bar": bar, "close": cl[-1][4],
                    "x": [round(v, 6) for v in x], "p": round(predict(st["w"], x), 4),
                    "p_base": round((st["ups"] + 1) / (st["n"] + 2), 4), "learned_from": st["n"]}
            _append(repo / FILE, lines, "FORECAST", data, now)
            added += 1
    return added


# ---------------------------------------------------------------- statistics
def _tstat(d: list) -> float:
    n = len(d)
    if n < 2:
        return 0.0
    m = sum(d) / n
    s = math.sqrt(sum((v - m) ** 2 for v in d) / (n - 1))
    return m / (s / math.sqrt(n)) if s > 0 else (math.inf if m > 0 else 0.0)


def _block(rows: list) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    bl = sum((r["p"] - r["y"]) ** 2 for r in rows) / n
    bb = sum((r["p_base"] - r["y"]) ** 2 for r in rows) / n
    acc = sum(1 for r in rows if (r["p"] >= 0.5) == (r["y"] == 1)) / n
    return {"n": n, "brier_learner": round(bl, 5), "brier_baseline": round(bb, 5),
            "skill": round(1 - bl / bb, 4) if bb > 0 else None, "accuracy": round(acc, 4),
            "rose_share": round(sum(r["y"] for r in rows) / n, 4)}


def stats(lines: list) -> dict:
    fc = {e["data"]["id"]: e["data"] for e in lines if e["kind"] == "FORECAST"}
    rows = []
    for e in lines:
        if e["kind"] == "OUTCOME" and e["data"]["id"] in fc:
            d = fc[e["data"]["id"]]
            rows.append({**d, "y": e["data"]["y"]})
    out = {"version": VERSION, "forecasts": len(fc), "settled": len(rows), "horizons": {}}
    for h in HORIZONS:
        hr = [r for r in rows if r["h"] == h]
        non = [r for r in hr if _hour_index(r["bar"]) % h == 0]
        d = [(r["p_base"] - r["y"]) ** 2 - (r["p"] - r["y"]) ** 2 for r in non]
        t = _tstat(d)
        v = "INSUFFICIENT" if len(non) < MIN_N else ("USEFUL" if sum(d) > 0 and t >= T_MIN else "NOT_USEFUL")
        cal = []
        for lo, hi in ((0, .4), (.4, .47), (.47, .53), (.53, .6), (.6, 1.01)):
            b = [r for r in hr if lo <= r["p"] < hi]
            cal.append({"p_from": lo, "p_to": min(hi, 1.0), "n": len(b),
                        "rose": round(sum(r["y"] for r in b) / len(b), 3) if b else None})
        out["horizons"][f"{h}h"] = {
            "all": _block(hr), "non_overlapping": _block(non), "t_stat": round(t, 2) if math.isfinite(t) else None,
            "verdict": v, "calibration": cal,
            "by_asset": {a: _block([r for r in hr if r["asset"] == a]) for a in ASSETS}}
    return out


def apply(repo: str = ".", now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rp = Path(repo)
    lines = _load(rp / FILE)
    (rp / "studies").mkdir(exist_ok=True)
    mp = rp / MODEL
    model = json.loads(mp.read_text()) if mp.exists() else None
    if model is None:
        model = {}
        bootstrap(model, rp, now)
    scored = settle(rp, now, lines, model)
    added = record(rp, now, lines, model)
    mp.write_text(json.dumps(model, sort_keys=True) + "\n")
    st = stats(lines)
    st["last_run"] = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "added": added, "settled": scored}
    (rp / STATS).write_text(json.dumps(st, indent=1, ensure_ascii=False) + "\n")
    return st


if __name__ == "__main__":
    import sys
    try:
        r = apply(sys.argv[1] if len(sys.argv) > 1 else ".")
        print("forecast:", r["last_run"])
    except Exception as e:  # noqa: BLE001  (never blocks the range ledger)
        print("forecast failed:", e)
