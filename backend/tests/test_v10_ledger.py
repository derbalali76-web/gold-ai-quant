"""Public trust ledger: append-only hash chain, no look-ahead, conservative outcomes, honest stats."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ledger", ROOT / "ledger" / "ledger.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

T0 = datetime(2026, 11, 16, 9, 30, tzinfo=timezone.utc)  # a Monday


def h1(start, rows):
    return [[L.iso(start + timedelta(hours=i)), *r] for i, r in enumerate(rows)]


def snap(now, recs=(), price=2000.0, bars=None, brief=None, closed=False):
    return {"as_of": L.iso(now), "symbol": "XAUUSD", "price": price, "cost": 0.0, "market_closed": closed,
            "model_version": "m1", "recommendations": list(recs), "brief": brief,
            "bars": bars or {"H1": [], "D1": []}}


BUY = {"horizon": "HOURS", "side": "BUY", "order": "MARKET", "stop": 1990.0, "target": 2020.0,
       "valid_until": L.iso(T0 + timedelta(hours=8)), "model_version": "m1"}


def test_target_win_and_chain(tmp_path):
    led = L.Ledger(tmp_path)
    led.ingest(snap(T0, [BUY]), T0)
    assert [e["kind"] for e in led.entries] == ["REC"]
    # the bar that contains the recording time is ignored; later bars reach the target
    later = T0 + timedelta(hours=3)
    bars = h1(datetime(2026, 11, 16, 9, tzinfo=timezone.utc),
              [[2000, 2030, 1950, 2000], [2000, 2005, 1995, 2003], [2003, 2021, 2000, 2018]])
    new = led.ingest(snap(later, [BUY], bars={"H1": bars, "D1": []}), later + timedelta(minutes=1))
    res = [e for e in new if e["kind"] == "RESULT"]
    assert res and res[0]["data"]["outcome"] == "TARGET" and res[0]["data"]["r"] == 2.0
    assert L.Ledger(tmp_path).verify() == []
    s = L.stats(led.entries, later)
    assert s["recommendations"]["completed"] == 1 and s["recommendations"]["win_rate"] == 1.0
    assert s["by_model"]["m1"]["wins"] == 1


def test_both_touched_counts_as_stop_and_no_duplicate_open(tmp_path):
    led = L.Ledger(tmp_path)
    led.ingest(snap(T0, [BUY]), T0)
    led.ingest(snap(T0 + timedelta(minutes=30), [BUY]), T0 + timedelta(minutes=30))
    assert sum(e["kind"] == "REC" for e in led.entries) == 1  # one open plan per horizon
    t = T0 + timedelta(hours=2)
    bars = h1(datetime(2026, 11, 16, 10, tzinfo=timezone.utc), [[2000, 2025, 1985, 2000]])
    led.ingest(snap(t, bars={"H1": bars, "D1": []}), t)
    r = [e for e in led.entries if e["kind"] == "RESULT"][0]["data"]
    assert r["outcome"] == "STOP" and r["r"] == -1.0


def test_tamper_detected(tmp_path):
    led = L.Ledger(tmp_path)
    led.ingest(snap(T0, [BUY]), T0)
    led.ingest(snap(T0 + timedelta(days=1), brief=None), T0 + timedelta(days=1))
    lines = (tmp_path / "ledger.jsonl").read_text().splitlines()
    e = json.loads(lines[0])
    e["data"]["target"] = 2010.0
    (tmp_path / "ledger.jsonl").write_text(json.dumps(e) + "\n" + "\n".join(lines[1:]) + "\n")
    assert any("hash" in x for x in L.Ledger(tmp_path).verify())


def test_stale_snapshot_records_nothing(tmp_path):
    led = L.Ledger(tmp_path)
    led.ingest(snap(T0, [BUY]), T0 + timedelta(hours=3))
    assert led.entries == []


def test_brief_only_today_and_scored_at_close(tmp_path):
    led = L.Ledger(tmp_path)
    b = {"date": "2026-11-16", "bias": "UP", "price": 2000.0, "scenarios": []}
    led.ingest(snap(T0, brief=dict(b, date="2026-11-13")), T0)  # an older day's brief: its close may be known
    assert led.entries == []
    led.ingest(snap(T0, brief=b), T0)
    led.ingest(snap(T0 + timedelta(hours=1), brief=b), T0 + timedelta(hours=1))
    assert sum(e["kind"] == "BRIEF" for e in led.entries) == 1
    nxt = datetime(2026, 11, 17, 1, tzinfo=timezone.utc)
    d1 = [[L.iso(datetime(2026, 11, 16, tzinfo=timezone.utc)), 1995, 2012, 1990, 2008]]
    led.ingest(snap(nxt, bars={"H1": [], "D1": d1}), nxt)
    r = [e for e in led.entries if e["kind"] == "BRIEF_RESULT"][0]["data"]
    assert r["outcome"] == "CORRECT"
    s = L.stats(led.entries, nxt)
    assert s["analysis"]["accuracy"] == 1.0 and s["recommendations"]["completed"] == 0


def test_limit_not_filled_excluded(tmp_path):
    led = L.Ledger(tmp_path)
    lim = dict(BUY, order="LIMIT", entry_low=1994.0, entry_high=1995.0,
               valid_until=L.iso(T0 + timedelta(hours=3)))
    led.ingest(snap(T0, [lim]), T0)
    t = T0 + timedelta(hours=5)
    bars = h1(datetime(2026, 11, 16, 10, tzinfo=timezone.utc), [[2000, 2004, 1998, 2001]] * 4)
    led.ingest(snap(t, bars={"H1": bars, "D1": []}), t)
    r = [e for e in led.entries if e["kind"] == "RESULT"][0]["data"]
    assert r["outcome"] == "NOT_FILLED"
    assert L.stats(led.entries, t)["recommendations"]["completed"] == 0


def test_public_snapshot_endpoint_feeds_ledger(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from goldquant.api import create_app, Settings
    from goldquant.providers.demo import DemoProvider
    monkeypatch.setenv("GOLDQUANT_BG_REFRESH", "0")
    st = Settings.from_env(str(tmp_path))
    c = TestClient(create_app(str(tmp_path / "g.db"), settings=st, live_provider=DemoProvider()))
    r = c.get("/public/snapshot")  # no token required
    assert r.status_code == 200
    s = r.json()
    assert set(s) >= {"as_of", "price", "recommendations", "brief", "bars", "model_version"}
    assert isinstance(s["bars"]["H1"], list)
    for rec in s["recommendations"]:
        assert rec["stop"] and rec["target"]
    (tmp_path / "led").mkdir()
    led = L.Ledger(tmp_path / "led")
    led.ingest(s, L.ts(s["as_of"]) + timedelta(minutes=1))
    assert led.verify() == []


def test_weekend_prints_are_not_bars(tmp_path):
    led = L.Ledger(tmp_path)
    sat = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    bars = h1(datetime(2026, 11, 13, 19, tzinfo=timezone.utc), [[2000, 2001, 1999, 2000]] * 10)
    led.ingest(snap(sat, bars={"H1": bars, "D1": []}, closed=True), sat)
    kept = sorted(led.bars["H1"])
    # November = New York winter time: the week closes Friday 22:00 UTC
    assert kept == ["2026-11-13T19:00:00Z", "2026-11-13T20:00:00Z", "2026-11-13T21:00:00Z"]


def test_provider_drops_weekend_bars():
    import pandas as pd
    from goldquant.providers.base import closed_bars
    i = pd.date_range("2026-11-13 19:00", periods=8, freq="h", tz="UTC").append(
        pd.date_range("2026-11-15 21:00", periods=3, freq="h", tz="UTC"))
    df = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=i)
    out = closed_bars(df, "H1", pd.Timestamp("2026-11-16", tz="UTC"))
    assert [t.hour for t in out.index] == [19, 20, 21, 23]  # winter: Fri close 22:00 UTC, Sun open 23:00 UTC


def test_weekend_without_quote_uses_last_session_close():
    from goldquant.engine import DecisionEngine
    from goldquant.store import Store
    from goldquant.providers.demo import DemoProvider
    from goldquant.schemas import Mode

    class NoWeekendQuote(DemoProvider):
        def quote(self, as_of):
            return None
    eng = DecisionEngine(Store())
    sat = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    d = eng.decide(NoWeekendQuote(), Mode.DEMO, sat)
    assert d.market_closed and d.quote is not None
    assert d.quote_timestamp_utc is not None and d.quote_timestamp_utc <= sat  # the last real bar, never "now"
