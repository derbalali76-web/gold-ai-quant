"""Perpetual-futures crowding for BTC / ETH / SOL (owner 2026-11-26): funding rate and open interest.

Source: Hyperliquid's public info API (no key, not geo-blocked): one POST returns every perpetual's hourly funding
rate, open interest (in coins) and mark price. Cached for 10 minutes; hourly samples of open interest are kept in
memory so a 24 h change can be shown once the server has been up for a day. Display only: no idea or score uses it.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import httpx

URL = "https://api.hyperliquid.xyz/info"
ASSETS = ("BTC", "ETH", "SOL")
TTL_S = 600
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": None}
_oi_hist: dict[str, list[tuple[float, float]]] = {a: [] for a in ASSETS}


def _post() -> list:
    r = httpx.post(URL, json={"type": "metaAndAssetCtxs"}, timeout=10.0,
                   headers={"User-Agent": "GoldAIQuant/0.3 (personal research)"})
    r.raise_for_status()
    return r.json()


def parse(payload: list, now: float) -> dict:
    meta, ctxs = payload[0], payload[1]
    names = [u.get("name") for u in meta.get("universe", [])]
    out = {}
    for a in ASSETS:
        if a not in names:
            continue
        c = ctxs[names.index(a)]
        try:
            funding = float(c.get("funding"))
            mark = float(c.get("markPx"))
            oi_usd = float(c.get("openInterest")) * mark
        except (TypeError, ValueError):
            continue
        h = _oi_hist[a]
        if not h or now - h[-1][0] >= 3600:
            h.append((now, oi_usd))
            del h[:-30]
        old = next((v for t, v in h if now - t >= 23 * 3600), None)
        out[a] = {"funding_hourly": funding, "funding_annual_pct": round(funding * 24 * 365 * 100, 1),
                  "open_interest_usd": round(oi_usd), "mark": mark,
                  "oi_change_24h_pct": round(100 * (oi_usd / old - 1), 2) if old else None}
    return out


def snapshot(fetch: Callable[[], list] = _post, now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    with _lock:
        if _cache["data"] is not None and now - _cache["at"] < TTL_S:
            return _cache["data"]
    try:
        data = {"state": "OK", "source": "hyperliquid", "assets": parse(fetch(), now),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}
    except Exception as e:  # noqa: BLE001
        data = {"state": "UNAVAILABLE", "source": "hyperliquid", "assets": {}, "error": type(e).__name__}
    with _lock:
        _cache.update(at=now, data=data)
    return data
