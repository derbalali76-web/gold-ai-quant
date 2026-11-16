#!/usr/bin/env python3
"""Independent issuer: the crypto price ranges and the high / low live validation are computed HERE, inside the
ledger workflow, so the record does not depend on the free app server being awake (it sleeps, restarts and is
redeployed; a missed issue time can never be recorded later, so a sleeping server would leave holes in the sample).

Same inputs and formulas as the app server (backend goldquant/price_range.live and goldquant/hilo.live):
  * the last 1000 hourly bars from Binance's public market-data mirror (data-api.binance.vision, no key), closed only;
  * the published weekly model parameters (models/range_models.json, models/hilo_models.json in the app repository);
  * features of the last CLOSED bar: log realised variance over 4 / 24 / 168 / 672 bars scaled to the horizon,
    hour of day (4 h only), weekend flag; scale s = exp(x . beta / 2);
  * range = close * exp(q10 * s / 100) .. close * exp(q90 * s / 100);
  * high / low bounds = model (qd * s, qu * s), B1 (exported 365-day quantiles), B2 (+/- 1.645 * EWMA sigma * sqrt H).
An equivalence test in the app repository (backend/tests/test_v27_issuer.py) checks this file against the server code.

Issue times: every 4 h on the hour (00/04/.../20 UTC; the 1-day and 1-week times are among them). A run computes the
latest issue time whose 75-minute recording window is still open, from the bars closed AT that time — so if the run
of that hour was missed, the next one records exactly what an on-time run would have (deterministic: no choice is
involved, and parameters published after the issue time are never used for it).

Standard library only (anyone can re-run it). Writes issue_<ASSET>.json, shaped like a server snapshot, which
`ledger.py update` ingests FIRST (the server's snapshot is the backup; the first recorded issue wins). It carries
closed bars, `ranges` and `hilo` — and "price": null, so it can never create a recommendation or a daily analysis:
those come only from the app.

usage: python3 issue.py OUT_DIR
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

KLINES = "https://data-api.binance.vision/api/v3/klines"
MODELS = "https://raw.githubusercontent.com/derbalali76-web/gold-ai-quant/main/models/"
SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
HILO_CASES = {"BTC": ("4h", "24h"), "ETH": ("4h", "24h")}  # hilo.LIVE_CASES (pre-registered)
WINDOWS = (4, 24, 168, 672)  # crypto: 4 bars / day / week / 4 weeks
LAMBDA = 0.94
Z90, Z95 = 1.2816, 1.6449
SOURCE = "ledger-action"
HOUR = timedelta(hours=1)
FRESH = timedelta(minutes=75)  # ledger.RANGE_FRESH: an issue is recorded only within this time of its issue time


def get_json(url: str, tries: int = 3, timeout: float = 30.0):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ai-quant-ledger/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            err = exc
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url}: {err}")


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def closed_bars(rows: list, step: timedelta, now: datetime) -> list[tuple[datetime, float, float, float, float]]:
    """Binance kline rows -> (open time, o, h, l, c), only bars whose close time has passed."""
    out = []
    for r in rows:
        t = datetime.fromtimestamp(int(r[0]) / 1000, tz=timezone.utc)
        if t + step <= now:
            out.append((t, float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    out.sort(key=lambda b: b[0])
    return out


def features(bars: list, H: int) -> dict | None:
    """Features of the decision at the close of the last bar (price_range.frame, last row)."""
    if len(bars) < WINDOWS[-1] + 5:
        return None
    c = [b[4] for b in bars]
    r2 = [None] + [(math.log(c[i]) - math.log(c[i - 1])) ** 2 for i in range(1, len(c))]
    f = {}
    for k, w in zip(("rv4", "rvd", "rvw", "rvm"), WINDOWS):
        f[k] = math.log(sum(r2[-w:]) * 1e4 * H / w + 1e-6)
    t = bars[-1][0] + HOUR
    f["hs"], f["hc"] = math.sin(2 * math.pi * t.hour / 24), math.cos(2 * math.pi * t.hour / 24)
    f["wk"] = 1.0 if t.weekday() >= 5 else 0.0
    ew = None  # EWMA(0.94) of squared hourly returns, started at the first return (pandas adjust=False)
    for x in r2[1:]:
        ew = x if ew is None else LAMBDA * ew + (1 - LAMBDA) * x
    f["sigma_h"] = math.sqrt(ew * H) * 100  # sigma * sqrt(H) in percent (the B2 baseline)
    f["t"], f["close"] = t, c[-1]
    return f


def scale(params: dict, f: dict) -> float | None:
    x = [1.0] + [f[k] for k in params["cols"]]
    if len(x) != len(params["beta"]) or not all(math.isfinite(v) for v in x):
        return None
    return math.exp(sum(a * b for a, b in zip(x, params["beta"])) / 2)


def params_sha(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def range_live(params: dict, bars: list) -> dict | None:
    H = int(params["bars"])
    f = features(bars, H)
    s = scale(params, f) if f else None
    if s is None:
        return None
    c, lo, hi = f["close"], params["q10"] * s, params["q90"] * s
    return {"horizon": params["horizon"], "bars": H, "issued_at": iso(f["t"]), "close_at_issue": c,
            "low": c * math.exp(lo / 100), "high": c * math.exp(hi / 100), "lo_pct": round(lo, 4),
            "hi_pct": round(hi, 4), "version": params["version"], "params_sha": params_sha(params),
            "trained_until": params.get("trained_until")}


def hilo_live(params: dict, bars: list) -> dict | None:
    H = int(params["bars"])
    f = features(bars, H)
    s = scale(params, f) if f else None
    if s is None or not math.isfinite(f["sigma_h"]):
        return None
    c, sig = f["close"], f["sigma_h"]
    pct = {"m": (params["qd"] * s, params["qu"] * s), "b1": (params["b1_down"], params["b1_up"]),
           "b2": (-Z95 * sig, Z95 * sig)}
    out = {"horizon": params["horizon"], "bars": H, "issued_at": iso(f["t"]), "expires_at": iso(f["t"] + H * HOUR),
           "close_at_issue": c, "version": params["version"], "params_sha": params_sha(params),
           "trained_until": params.get("trained_until")}
    for k, (lo, hi) in pct.items():
        out[f"{k}_lower"], out[f"{k}_upper"] = c * math.exp(lo / 100), c * math.exp(hi / 100)
    return out


def due_slot(h1: list, now: datetime) -> datetime | None:
    """The latest issue time (every 4 h on the hour; the 1-day and 1-week times are among them) whose recording window
    is still open. If the run for that hour was missed, the next run can still record it — from the bars closed AT
    that time only, so it is exactly what an on-time run would have computed."""
    if not h1:
        return None
    last = h1[-1][0] + HOUR
    t = last.replace(hour=last.hour - last.hour % 4, minute=0, second=0, microsecond=0)
    return t if timedelta(0) <= now - t <= FRESH else None


def issue(asset: str, h1: list, d1: list, ranges: dict, hilo: dict, now: datetime,
          published: dict | None = None) -> dict:
    """Snapshot-shaped record for one asset (no price: never a recommendation or a daily analysis).
    `published`: when each parameter file was exported; a late computation never uses parameters newer than its issue
    time (they could contain information from after it)."""
    rows = lambda bs: [[iso(b[0]), *(round(v, 4) for v in b[1:])] for b in bs]  # noqa: E731
    out = {"schema": 1, "asset": asset, "symbol": SYMBOLS[asset], "as_of": iso(now), "price": None,
           "source": SOURCE, "bars": {"H1": rows(h1[-120:]), "D1": rows(d1[-45:])}, "ranges": [], "hilo": []}
    slot = due_slot(h1, now)
    if slot is None:
        return out
    upto = [b for b in h1 if b[0] + HOUR <= slot]
    late = upto[-1][0] + HOUR < h1[-1][0] + HOUR if upto else True
    pub = published or {}

    def allowed(name: str) -> bool:
        p = pub.get(name)
        return not late or (p is not None and datetime.fromisoformat(p.replace("Z", "+00:00")) <= slot)

    if not upto or not allowed("range"):
        ranges = {}
    if not upto or not allowed("hilo"):
        hilo = {}
    h1 = upto
    for h, x in (ranges.get(asset) or {}).items():
        r = range_live(x["params"], h1) if x.get("params") else None
        if r is not None:
            out["ranges"].append(dict(r, qualified=bool(x.get("qualified")), holdout_coverage=x.get("holdout_coverage")))
    for h in HILO_CASES.get(asset, ()):
        x = (hilo.get(asset) or {}).get(h) or {}
        r = hilo_live(x["params"], h1) if x.get("params") else None
        if r is not None:
            out["hilo"].append(r)
    return out


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0] if argv else ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    ranges, hilo, problems, published = {}, {}, [], {}
    try:
        m = get_json(MODELS + "range_models.json")
        ranges, published["range"] = m.get("assets", {}), m.get("updated_at")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"range models: {exc}")
    try:
        m = get_json(MODELS + "hilo_models.json")
        hilo, published["hilo"] = m.get("assets", {}), m.get("updated_at")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"hilo models: {exc}")
    for asset, sym in SYMBOLS.items():
        try:
            now = datetime.now(timezone.utc)
            h1 = closed_bars(get_json(f"{KLINES}?symbol={sym}&interval=1h&limit=1000"), HOUR, now)
            d1 = closed_bars(get_json(f"{KLINES}?symbol={sym}&interval=1d&limit=46"), timedelta(days=1), now)
            snap = issue(asset, h1, d1, ranges, hilo, now, published)
            (out_dir / f"issue_{asset}.json").write_text(json.dumps(snap, separators=(",", ":")), encoding="utf-8")
            slot = due_slot(h1, now)
            print(f"{asset}: {len(h1)} hourly bars to {iso(h1[-1][0] + HOUR) if h1 else '-'}; issue time "
                  f"{iso(slot) if slot else 'none due'}: {len(snap['ranges'])} ranges, {len(snap['hilo'])} high/low")
        except Exception as exc:  # noqa: BLE001 — the server snapshot is still tried afterwards
            problems.append(f"{asset}: {exc}")
    for p in problems:
        print("ISSUER-PROBLEM", p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
