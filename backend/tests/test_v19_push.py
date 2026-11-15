import json
from types import SimpleNamespace as NS

import pytest

from goldquant.push import PushService

TOK = "f" * 40
CREDS = json.dumps({"project_id": "ai-quant-test"})


def dec(quote, events=(), closed=False, rec=None):
    plan = NS(recommendation=bool(rec), side=rec, entry_low=1.0, entry_high=2.0) if rec else None
    return NS(quote=quote, market_closed=closed, daily_brief=NS(events=list(events)),
              outlooks=[NS(horizon="HOURS", plan=plan)])


def svc(tmp_path, sent, alive=True):
    return PushService(tmp_path, creds_json=CREDS, sender=lambda t, p: (sent.append(p["message"]["data"]), alive)[1])


def test_not_configured_without_credentials(tmp_path):
    s = PushService(tmp_path, creds_json="")
    assert not s.configured and s.tick(lambda a: dec(1.0)) == {"configured": False, "sent": 0}
    bad = PushService(tmp_path / "b", creds_json="{not json")
    assert not bad.configured and "invalid FIREBASE_CREDENTIALS" in bad.error and "not json" not in bad.error


def test_price_alert_fires_once_and_is_removed(tmp_path):
    sent = []
    s = svc(tmp_path, sent)
    s.register(TOK, ["BTC"], [{"asset": "SOL", "dir": "BELOW", "price": 70.0, "label": "S1", "key": "k1"}], "ar")
    assert s.tick(lambda a: dec(71.0), force=True)["sent"] == 0
    assert s.tick(lambda a: dec(69.9), force=True)["sent"] == 1
    assert sent[-1]["type"] == "price" and sent[-1]["key"] == "k1"
    assert s.tick(lambda a: dec(69.0), force=True)["sent"] == 0
    assert s.devices()[0]["alerts"] == []


def test_scenario_event_dedupe_and_closed_market(tmp_path):
    sent = []
    s = svc(tmp_path, sent)
    s.register(TOK, ["XAU"], [], "fr")
    ev = NS(hour_utc="2026-11-15T14:00", kind="BEAR", level=4000.0, level_name="S1", target=3980.0, target_name="S2")
    assert s.tick(lambda a: dec(4001, [ev], closed=True), force=True)["sent"] == 0
    assert s.tick(lambda a: dec(4001, [ev]), force=True)["sent"] == 1
    assert s.tick(lambda a: dec(4001, [ev]), force=True)["sent"] == 0


def test_only_validated_recommendations_are_pushed(tmp_path):
    sent = []
    s = svc(tmp_path, sent)
    s.register(TOK, ["ETH"], [], "en")
    assert s.tick(lambda a: dec(3000), force=True)["sent"] == 0
    assert s.tick(lambda a: dec(3000, rec="BUY"), force=True)["sent"] == 1 and sent[-1]["type"] == "signal"


def test_dead_token_is_removed_and_tick_is_throttled(tmp_path):
    sent = []
    s = svc(tmp_path, sent, alive=False)
    s.register(TOK, [], [{"asset": "BTC", "dir": "ABOVE", "price": 1.0, "label": "R1"}], "ar")
    s.tick(lambda a: dec(2.0), force=True)
    assert s.devices() == []
    assert s.tick(lambda a: dec(2.0)).get("skipped") is True  # second call inside 45 s


def test_register_rejects_junk(tmp_path):
    s = svc(tmp_path, [])
    with pytest.raises(ValueError):
        s.register("short", [], [])
    r = s.register(TOK, ["BTC", "DOGE"], [{"asset": "X", "dir": "UP", "price": "a"}], "ar")
    assert r["assets"] == ["BTC"] and r["alerts"] == 0


def test_api_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from goldquant.api import Settings, create_app
    monkeypatch.setenv("GOLDQUANT_BG_REFRESH", "0")
    monkeypatch.setenv("GOLDQUANT_TOKEN", "secret-token-123")
    monkeypatch.delenv("FIREBASE_CREDENTIALS", raising=False)
    c = TestClient(create_app(str(tmp_path / "g.db"), settings=Settings.from_env(str(tmp_path))))
    assert c.post("/push/register", json={"token": TOK}).status_code == 401
    h = {"X-Goldquant-Token": "secret-token-123"}
    r = c.post("/push/register", json={"token": TOK, "assets": ["BTC"], "alerts": []}, headers=h).json()
    assert r["configured"] is False and r["assets"] == ["BTC"]
    assert c.get("/push/tick").json()["configured"] is False  # public, harmless
    st = c.get("/push/status", headers=h).json()
    assert st["devices"] == 1 and "private_key" not in json.dumps(st)
