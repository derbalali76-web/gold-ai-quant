"""Firebase Cloud Messaging (HTTP v1) for AI QUANT alerts.

What the server keeps per phone: an anonymous FCM token, the assets it follows, its one-tap price alerts and its
language. No e-mail, phone number or name. Phones re-register on every app open and every background run, so a
restart of the free server (which wipes its disk) heals itself within ~15 minutes.

Messages are DATA messages: the phone builds the localized text and removes a fired price alert from its own list.
Nothing here is a recommendation by itself: it relays price alerts the user set, scenario triggers and — only if one
ever exists — validated recommendations.

Credentials: env FIREBASE_CREDENTIALS = the service-account JSON (never logged, never returned by any endpoint).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("goldquant.push")
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
ASSETS = ("XAU", "BTC", "ETH", "SOL")
TICK_MIN_INTERVAL = 45.0
DEDUPE_HOURS = 30


class PushService:
    def __init__(self, data_dir: Path, creds_json: Optional[str] = None, sender: Optional[Callable] = None):
        self.db_path = Path(data_dir) / "push.sqlite"
        self._lock = threading.Lock()
        self._creds = None
        self.project_id = None
        self.error: Optional[str] = None
        self.last_tick: Optional[float] = None
        self.last_sent = 0
        self._sender = sender  # tests inject a fake sender
        raw = creds_json if creds_json is not None else os.getenv("FIREBASE_CREDENTIALS")
        if raw:
            try:
                info = json.loads(raw)
                self.project_id = info.get("project_id")
                if sender is None:
                    from google.oauth2 import service_account
                    self._creds = service_account.Credentials.from_service_account_info(info, scopes=[FCM_SCOPE])
            except Exception as exc:  # noqa: BLE001 — report the type only, never the content
                self.error = f"invalid FIREBASE_CREDENTIALS ({type(exc).__name__})"
                log.warning("push disabled: %s", self.error)
        with self._db() as c:
            c.execute("create table if not exists devices (token text primary key, assets text, alerts text, "
                      "lang text, updated real)")
            c.execute("create table if not exists sent (token text, key text, at real, primary key (token, key))")

    @property
    def configured(self) -> bool:
        return bool(self.project_id) and (self._creds is not None or self._sender is not None) and not self.error

    def _db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path, timeout=10)

    # ---------------------------------------------------------------- registration
    def register(self, token: str, assets: list, alerts: list, lang: str = "ar") -> dict:
        token = (token or "").strip()
        if not (20 <= len(token) <= 4096):
            raise ValueError("bad token")
        assets = [a for a in assets if a in ASSETS]
        clean = []
        for a in alerts[:30]:
            try:
                if a["asset"] in ASSETS and a["dir"] in ("ABOVE", "BELOW") and float(a["price"]) > 0:
                    clean.append({"asset": a["asset"], "dir": a["dir"], "price": float(a["price"]),
                                  "label": str(a.get("label", ""))[:20], "key": str(a.get("key", ""))[:80]})
            except (KeyError, TypeError, ValueError):
                continue
        with self._lock, self._db() as c:
            c.execute("insert or replace into devices values (?,?,?,?,?)",
                      (token, json.dumps(assets), json.dumps(clean), (lang or "ar")[:5], time.time()))
        return {"configured": self.configured, "assets": assets, "alerts": len(clean)}

    def unregister(self, token: str) -> None:
        with self._lock, self._db() as c:
            c.execute("delete from devices where token=?", (token,))
            c.execute("delete from sent where token=?", (token,))

    def devices(self) -> list[dict]:
        with self._db() as c:
            rows = c.execute("select token, assets, alerts, lang from devices").fetchall()
        return [{"token": t, "assets": json.loads(a), "alerts": json.loads(al), "lang": lg} for t, a, al, lg in rows]

    def _seen(self, c, token: str, key: str) -> bool:
        return c.execute("select 1 from sent where token=? and key=?", (token, key)).fetchone() is not None

    # ---------------------------------------------------------------- sending
    def _access_token(self) -> str:
        from google.auth.transport.requests import Request
        if not self._creds.valid:
            self._creds.refresh(Request())
        return self._creds.token

    def send(self, token: str, data: dict) -> bool:
        """Returns False when the token is dead (the device is then removed)."""
        payload = {"message": {"token": token, "data": {k: str(v) for k, v in data.items()},
                               "android": {"priority": "high", "ttl": "3600s"}}}
        if self._sender is not None:
            return bool(self._sender(token, payload))
        import httpx
        try:
            r = httpx.post(f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send",
                           headers={"Authorization": f"Bearer {self._access_token()}"}, json=payload, timeout=15)
        except Exception as exc:  # noqa: BLE001
            self.error = f"send failed ({type(exc).__name__})"
            log.warning("push send failed: %s", type(exc).__name__)
            return True
        if r.status_code in (404, 410) or (r.status_code == 400 and "UNREGISTERED" in r.text):
            return False
        if r.status_code >= 300:
            log.warning("push send HTTP %s", r.status_code)
        else:
            self.error = None
        return True

    # ---------------------------------------------------------------- the periodic check
    def tick(self, get_decision: Callable[[str], object], force: bool = False) -> dict:
        """Check every registered phone once; throttled so outside pings cannot spam the server."""
        now = time.time()
        if not force and self.last_tick and now - self.last_tick < TICK_MIN_INTERVAL:
            return {"skipped": True, "configured": self.configured}
        self.last_tick = now
        if not self.configured:
            return {"configured": False, "sent": 0}
        devs = self.devices()
        need = sorted({a for d in devs for a in d["assets"]} | {al["asset"] for d in devs for al in d["alerts"]})
        decisions = {}
        for a in need:
            try:
                decisions[a] = get_decision(a)
            except Exception as exc:  # noqa: BLE001
                log.warning("push tick: decision %s failed (%s)", a, type(exc).__name__)
        sent = 0
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        with self._lock, self._db() as c:
            c.execute("delete from sent where at < ?", (now - DEDUPE_HOURS * 3600,))
            for dv in devs:
                tok, msgs = dv["token"], []
                for al in dv["alerts"]:  # 1) one-tap price alerts the user set
                    d = decisions.get(al["asset"])
                    q = getattr(d, "quote", None) if d is not None else None
                    if q is None or getattr(d, "market_closed", False):
                        continue
                    hit = q >= al["price"] if al["dir"] == "ABOVE" else q <= al["price"]
                    key = "price|" + (al.get("key") or f"{al['asset']}|{al['dir']}|{al['price']}")
                    if hit and not self._seen(c, tok, key):
                        msgs.append((key, {"type": "price", "asset": al["asset"], "level": al["price"],
                                           "label": al["label"], "price": q, "key": al.get("key", "")}))
                for a in dv["assets"]:
                    d = decisions.get(a)
                    if d is None:
                        continue
                    b = getattr(d, "daily_brief", None)  # 2) a scenario triggered on the last closed hour
                    for e in (getattr(b, "events", None) or []) if b is not None and not d.market_closed else []:
                        key = f"event|{a}|{day}|{e.hour_utc}|{e.kind}|{e.level_name}"
                        if not self._seen(c, tok, key):
                            msgs.append((key, {"type": "event", "asset": a, "kind": e.kind, "level": e.level,
                                               "level_name": e.level_name, "target": e.target or "",
                                               "target_name": e.target_name or ""}))
                    for o in getattr(d, "outlooks", None) or []:  # 3) a VALIDATED recommendation (if ever)
                        p = o.plan
                        if p is not None and p.recommendation and p.side in ("BUY", "SELL"):
                            key = f"signal|{a}|{o.horizon}|{p.side}|{p.entry_low}|{p.entry_high}"
                            if not self._seen(c, tok, key):
                                msgs.append((key, {"type": "signal", "asset": a, "horizon": o.horizon,
                                                   "side": p.side}))
                for key, data in msgs[:5]:
                    ok = self.send(tok, data)
                    if not ok:
                        c.execute("delete from devices where token=?", (tok,))
                        break
                    c.execute("insert or replace into sent values (?,?,?)", (tok, key, now))
                    sent += 1
                    if data["type"] == "price":  # fired once: drop it on the server too
                        dv["alerts"] = [x for x in dv["alerts"] if "price|" + (x.get("key") or
                                        f"{x['asset']}|{x['dir']}|{x['price']}") != key]
                        c.execute("update devices set alerts=? where token=?", (json.dumps(dv["alerts"]), tok))
        self.last_sent = sent
        return {"configured": True, "devices": len(devs), "sent": sent}

    def status(self) -> dict:
        return {"configured": self.configured, "project": self.project_id, "devices": len(self.devices()),
                "last_tick_age_s": round(time.time() - self.last_tick) if self.last_tick else None,
                "last_sent": self.last_sent, "error": self.error}
