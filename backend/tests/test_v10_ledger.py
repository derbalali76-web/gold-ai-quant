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
    kept = sorted(led.bars[("XAU", "H1")])
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


def test_crypto_has_its_own_record_and_trades_on_sunday(tmp_path):
    led = L.Ledger(tmp_path)
    sun = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)
    b = {"date": "2026-11-15", "bias": "DOWN", "price": 90000.0, "scenarios": []}
    s = snap(sun, brief=b, price=90000.0)
    s["asset"] = "BTC"
    s["bars"] = {"H1": h1(datetime(2026, 11, 15, 6, tzinfo=timezone.utc), [[90100, 90200, 89900, 90000]] * 3), "D1": []}
    led.ingest(s, sun)
    assert [e["data"]["asset"] for e in led.entries] == ["BTC"]
    assert len(led.bars[("BTC", "H1")]) == 3  # weekend bars are real for crypto
    nxt = datetime(2026, 11, 16, 1, tzinfo=timezone.utc)
    s2 = dict(s, as_of=L.iso(nxt), brief=None, bars={"H1": [], "D1": [[L.iso(datetime(2026, 11, 15, tzinfo=timezone.utc)), 90500, 90600, 89000, 89500]]})
    led.ingest(s2, nxt)
    st = L.stats(led.entries, nxt)
    assert st["assets"]["BTC"]["analysis"]["correct"] == 1 and st["analysis"]["scored"] == 0  # gold untouched
    assert L.Ledger(tmp_path).verify() == []


def test_live_guard_switches_off_a_losing_horizon(tmp_path, monkeypatch):
    import json as _json
    from fastapi.testclient import TestClient
    from goldquant import api as API
    from goldquant.providers.demo import DemoProvider
    from goldquant.providers import http as H
    monkeypatch.setenv("GOLDQUANT_BG_REFRESH", "0")
    stats = {"chain_head": "x", "by_horizon": {"WEEK": {"completed": 25, "avg_r": -0.2}}}

    class R:
        text = _json.dumps(stats)
    monkeypatch.setattr(H.HttpClient, "get", lambda self, url, params=None: R())
    app = API.create_app(str(tmp_path / "g.db"), settings=API.Settings.from_env(str(tmp_path)), live_provider=DemoProvider())
    c = TestClient(app)
    token = API.Settings.from_env(str(tmp_path)).token
    d = c.get("/decision?mode=LIVE", headers={"X-Goldquant-Token": token or ""}).json()
    week = next(o for o in d["outlooks"] if o["horizon"] == "WEEK")
    assert week["validated"] is False and "25" in (week["validation_ar"] or "")
    assert not (week.get("plan") or {}).get("recommendation")


def test_crash_reports_are_counted_in_the_public_snapshot(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from goldquant.api import create_app, Settings
    from goldquant.providers.demo import DemoProvider
    monkeypatch.setenv("GOLDQUANT_BG_REFRESH", "0")
    st = Settings.from_env(str(tmp_path))
    c = TestClient(create_app(str(tmp_path / "g.db"), settings=st, live_provider=DemoProvider()))
    h = {"X-Goldquant-Token": st.token or ""}
    assert c.post("/crash", json={"trace": "java.lang.X at y", "app": "0.3.0 (150)", "android": 34}, headers=h).status_code == 200
    assert c.get("/public/snapshot").json()["app_crashes_7d"] == 1
    assert c.get("/crashes", headers=h).json()[0]["app"] == "0.3.0 (150)"


# ---------------- strategy scenarios (CASH / HOLDING), experimental layer
def _brief_snap(now, price=2000.0, asset="XAU"):
    b = {"date": now.date().isoformat(), "bias": "DOWN", "price": price,
         "scenarios": [{"kind": "BEAR", "trigger": 1990.0, "trigger_level": "S1", "target": 1980.0, "target_level": "S2"},
                       {"kind": "BULL", "trigger": 2010.0, "trigger_level": "R1", "target": 2020.0, "target_level": "R2"}]}
    s = snap(now, brief=b, price=price)
    s["asset"], s["cost"] = asset, 0.5
    return s


def _scen(led, name):
    sc = next(e for e in led.entries if e["kind"] == "SCENARIO" and e["data"]["strategy"] == name)
    return sc, next((e for e in led.entries if e["kind"] == "SCENARIO_RESULT" and e["data"]["ref"] == sc["seq"]), None)


def test_scenarios_registered_with_the_forecast_and_ids_linked(tmp_path):
    led = L.Ledger(tmp_path)
    led.ingest(_brief_snap(T0), T0)
    br = next(e for e in led.entries if e["kind"] == "BRIEF")
    scs = [e for e in led.entries if e["kind"] == "SCENARIO"]
    assert {e["data"]["strategy"] for e in scs} == set(L.STRATEGIES)
    assert all(e["recorded_at"] == br["recorded_at"] and e["data"]["fid"] == br["data"]["fid"] for e in scs)
    assert all(e["data"]["sid"].startswith(br["data"]["fid"] + ":") and e["data"]["experimental"] for e in scs)
    assert led.verify() == []


def test_sell_rebuy_needs_a_cheaper_buyback_not_just_a_falling_price(tmp_path):
    led = L.Ledger(tmp_path)
    led.ingest(_brief_snap(T0), T0)
    # closes below S1 at 1989 (sell), price never reaches S2 1980 and ends at 1988.8: falling price, but the
    # forced buy-back is only 0.2 cheaper -> after 0.5 cost the strategy LOSES vs holding
    rows = [[1995, 1996, 1992, 1993], [1993, 1993, 1988, 1989]] + [[1989, 1990, 1988.5, 1988.8]] * 30
    t = T0 + timedelta(hours=40)
    led.ingest(dict(snap(t), asset="XAU", bars={"H1": h1(datetime(2026, 11, 16, 10, tzinfo=timezone.utc), rows), "D1": []}), t)
    _, res = _scen(led, "HOLD_SELL_REBUY")
    assert res["data"]["outcome"] == "TRIGGERED" and res["data"]["rebuy_how"] == "FORCED_AT_EXPIRY"
    assert res["data"]["return_pct"] < 0 and res["data"]["win"] is False


def test_not_triggered_is_recorded_and_cash_compared_with_buying_now(tmp_path):
    led = L.Ledger(tmp_path)
    led.ingest(_brief_snap(T0), T0)
    rows = [[2000, 2004, 1996, 2003]] * 30  # never touches S1: nothing triggers; price rose
    t = T0 + timedelta(hours=40)
    led.ingest(dict(snap(t), asset="XAU", bars={"H1": h1(datetime(2026, 11, 16, 10, tzinfo=timezone.utc), rows), "D1": []}), t)
    _, dip = _scen(led, "CASH_BUY_DIP")
    _, hold = _scen(led, "HOLD_SELL_REBUY")
    _, wait = _scen(led, "CASH_WAIT_LOWER")
    assert dip["data"]["outcome"] == "NOT_TRIGGERED" and dip["data"]["ref_buy_now_pct"] > 0 and not dip["data"]["beat_ref"]
    assert hold["data"]["outcome"] == "NOT_TRIGGERED" and hold["data"]["beat_ref"] is False
    assert wait["data"]["outcome"] == "NOT_TRIGGERED" and wait["data"]["advantage_pct"] < 0  # waiting missed the rise
    st = L.stats(led.entries, t)["scenarios"]
    assert st["experimental"] and st["assets"]["XAU"]["CASH_BUY_DIP"]["all"]["not_triggered"] == 1
    assert L.Ledger(tmp_path).verify() == []


def test_old_ledger_still_verifies_byte_for_byte(tmp_path):
    led = L.Ledger(tmp_path)
    led.ingest(snap(T0, [BUY]), T0)
    before = (tmp_path / "ledger.jsonl").read_text()
    led2 = L.Ledger(tmp_path)
    led2.ingest(_brief_snap(T0 + timedelta(minutes=30)), T0 + timedelta(minutes=30))
    assert (tmp_path / "ledger.jsonl").read_text().startswith(before)  # append-only: old lines untouched
    assert L.Ledger(tmp_path).verify() == []


def test_range_recorded_on_cadence_then_resolved_on_the_target_close(tmp_path):
    led = L.Ledger(tmp_path)
    issued = datetime(2026, 11, 17, 8, tzinfo=timezone.utc)  # Tuesday 08:00 = a 4 h cadence point
    rng = {"horizon": "4h", "bars": 4, "issued_at": L.iso(issued), "close_at_issue": 2000.0, "low": 1990.0,
           "high": 2010.0, "version": "range-har-0.1.0", "qualified": True}
    off = dict(rng, horizon="24h", issued_at=L.iso(issued))  # 08:00 is not a 24 h cadence point
    s = dict(snap(issued + timedelta(minutes=17)), ranges=[rng, off])
    led.ingest(s, issued + timedelta(minutes=17))
    r = [e for e in led.entries if e["kind"] == "RANGE"]
    assert len(r) == 1 and r[0]["data"]["horizon"] == "4h"
    led.ingest(s, issued + timedelta(minutes=30))  # never twice
    assert len([e for e in led.entries if e["kind"] == "RANGE"]) == 1
    late = dict(rng, issued_at=L.iso(issued - timedelta(hours=4)))  # too old to be a pre-recorded forecast
    led.ingest(dict(snap(issued + timedelta(minutes=20)), ranges=[late]), issued + timedelta(minutes=20))
    assert len([e for e in led.entries if e["kind"] == "RANGE"]) == 1
    # issue bar 07:00, then 4 more bars; the 4th bar after the issue bar closes at 2012 -> ABOVE
    bars = h1(datetime(2026, 11, 17, 7, tzinfo=timezone.utc),
              [[2000, 2001, 1999, 2000], [2000, 2004, 1998, 2003], [2003, 2006, 2001, 2005],
               [2005, 2009, 2004, 2008], [2008, 2013, 2007, 2012]])
    now = issued + timedelta(hours=5, minutes=17)
    led.ingest(dict(snap(now, bars={"H1": bars, "D1": []})), now)
    res = [e for e in led.entries if e["kind"] == "RANGE_RESULT"]
    assert len(res) == 1 and res[0]["data"]["outcome"] == "ABOVE" and res[0]["data"]["close"] == 2012.0
    st = L.stats(led.entries, now)["ranges"]["XAU"]["4h"]
    assert st["recorded"] == 1 and st["settled"] == 1 and st["inside"] == 0
    assert L.Ledger(tmp_path).verify() == []


def test_hilo_recorded_every_4h_then_scored_with_both_baselines(tmp_path):
    led = L.Ledger(tmp_path)
    issued = datetime(2026, 11, 17, 8, tzinfo=timezone.utc)
    r = {"horizon": "4h", "bars": 4, "issued_at": L.iso(issued), "close_at_issue": 100.0, "version": "hilo-har-0.1.0",
         "m_lower": 98.0, "m_upper": 102.0, "b1_lower": 97.0, "b1_upper": 103.0, "b2_lower": 99.0, "b2_upper": 101.0}
    s = dict(snap(issued + timedelta(minutes=17)), asset="BTC", hilo=[r, dict(r, horizon="1w")])
    led.ingest(s, issued + timedelta(minutes=17))
    h = [e for e in led.entries if e["kind"] == "HILO"]
    assert len(h) == 1 and h[0]["data"]["expires_at"] == L.iso(issued + timedelta(hours=4))
    led.ingest(dict(snap(issued), asset="XAU", hilo=[r]), issued + timedelta(minutes=18))  # gold is not a live case
    assert len([e for e in led.entries if e["kind"] == "HILO"]) == 1
    bars = h1(datetime(2026, 11, 17, 7, tzinfo=timezone.utc),
              [[100, 100.5, 99.5, 100], [100, 101.5, 99.6, 101], [101, 101.2, 100.2, 100.8],
               [100.8, 100.9, 98.5, 99], [99, 99.8, 98.9, 99.5]])
    now = issued + timedelta(hours=5, minutes=17)
    led.ingest(dict(snap(now, bars={"H1": bars, "D1": []}), asset="BTC"), now)
    res = [e for e in led.entries if e["kind"] == "HILO_RESULT"][0]["data"]
    assert res["high"] == 101.5 and res["low"] == 98.5
    assert res["m"]["inside"] and not res["b2"]["inside"] and res["b2"]["upper_exceeded"]
    st = L.stats(led.entries, now)["hilo"]["BTC"]["4h"]
    assert st["settled"] == 1 and st["m"]["inside"] == 1.0 and st["b2"]["inside"] == 0.0
    assert L.Ledger(tmp_path).verify() == []


# ---------------------------------------------------------------- completeness, provenance, cross-check (2026-11-16)
def _hilo_snap(now, issued, src=None, up=110.0):
    s = {"as_of": L.iso(now), "asset": "BTC", "price": None, "bars": {"H1": [], "D1": []}, "ranges": [],
         "hilo": [{"horizon": "4h", "bars": 4, "issued_at": L.iso(issued), "close_at_issue": 100.0,
                   "version": "hilo-har-0.1.0", "params_sha": "abc", "m_lower": 95.0, "m_upper": up,
                   "b1_lower": 96.0, "b1_upper": 104.0, "b2_lower": 97.0, "b2_upper": 103.0}]}
    if src:
        s["source"] = src
    return s


def test_completeness_counts_missed_issue_times():
    start = L.LIVE_START
    now = start + timedelta(hours=9, minutes=20)  # slots 20:00, 00:00, 04:00 are past their recording window
    e = {"kind": "HILO", "data": {"asset": "BTC", "horizon": "4h", "issued_at": L.iso(start), "source": "ledger-action"}}
    c = L.completeness([e], now)["cases"]
    assert c["HILO BTC 4h"] == {"expected": 3, "recorded": 1, "rate": 0.3333, "missed_24h": 2,
                                "by_source": {"ledger-action": 1},
                                "missed_last": [L.iso(start + timedelta(hours=4)), L.iso(start + timedelta(hours=8))]}
    assert c["RANGE BTC 24h"]["expected"] == 1 and c["RANGE BTC 1w"]["expected"] == 0


def test_gold_slots_only_when_the_market_was_open():
    sat = datetime(2026, 11, 21, 0, tzinfo=timezone.utc)  # Friday 19:00 New York: closed
    mon = datetime(2026, 11, 23, 0, tzinfo=timezone.utc)  # Sunday 19:00 New York: open
    slots = L.expected_slots("RANGE", "XAU", "24h", mon + timedelta(hours=2), start=sat - timedelta(days=1))
    assert sat not in slots and mon in slots and sat - timedelta(days=1) in slots


def test_first_recorded_issue_stands_and_disagreement_is_reported(tmp_path):
    led = L.Ledger(tmp_path)
    issued = datetime(2026, 11, 16, 20, tzinfo=timezone.utc)
    led.ingest(_hilo_snap(issued + timedelta(minutes=3), issued, "ledger-action"), issued + timedelta(minutes=3))
    led.ingest(_hilo_snap(issued + timedelta(minutes=9), issued, None, up=112.0), issued + timedelta(minutes=9))
    hl = [e for e in led.entries if e["kind"] == "HILO"]
    assert len(hl) == 1 and hl[0]["data"]["source"] == "ledger-action" and hl[0]["data"]["params_sha"] == "abc"
    assert hl[0]["data"]["m_upper"] == 110.0
    assert len(led.checks) == 1 and not led.checks[0]["agree"] and led.checks[0]["other"] == "server"
    led.ingest(_hilo_snap(issued + timedelta(minutes=12), issued, None), issued + timedelta(minutes=12))
    assert led.checks[-1]["agree"] and led.checks[-1]["max_rel_diff"] == 0.0
    assert led.verify() == []


def test_server_issue_recorded_when_the_issuer_failed(tmp_path):
    led = L.Ledger(tmp_path)
    issued = datetime(2026, 11, 16, 20, tzinfo=timezone.utc)
    led.ingest(_hilo_snap(issued + timedelta(minutes=50), issued), issued + timedelta(minutes=50))
    assert [e["data"]["source"] for e in led.entries if e["kind"] == "HILO"] == ["server"]
    led2 = L.Ledger(tmp_path / "late")
    led2.ingest(_hilo_snap(issued + timedelta(minutes=80), issued), issued + timedelta(minutes=80))  # too late
    assert not [e for e in led2.entries if e["kind"] == "HILO"]


def test_monitor_alerts_on_missed_issue_and_issuer_problem(tmp_path):
    spec_m = importlib.util.spec_from_file_location("monitor", ROOT / "ledger" / "monitor.py")
    M = importlib.util.module_from_spec(spec_m)
    spec_m.loader.exec_module(M)
    (tmp_path / "stats.json").write_text(json.dumps({"completeness": {"cases": {
        "HILO BTC 4h": {"expected": 6, "recorded": 5, "missed_24h": 1},
        "RANGE ETH 4h": {"expected": 6, "recorded": 6, "missed_24h": 0}}}}), encoding="utf-8")
    log = tmp_path / "issuer.txt"
    log.write_text("BTC: 999 hourly bars\nISSUER-PROBLEM ETH: timeout\n", encoding="utf-8")
    out = M.record_checks(tmp_path, str(log))
    assert any("HILO BTC 4h missed 1" in a for a in out) and any("independent issuer: ETH: timeout" in a for a in out)
    assert not any("RANGE ETH 4h" in a for a in out)


def test_monitor_needs_two_unreachable_runs_before_alerting(tmp_path, monkeypatch):
    import shutil
    for f in ("monitor.py",):
        shutil.copy(ROOT / "ledger" / f, tmp_path / f)
    spec_m = importlib.util.spec_from_file_location("monitor_tmp", tmp_path / "monitor.py")
    M = importlib.util.module_from_spec(spec_m)
    spec_m.loader.exec_module(M)
    (tmp_path / "snap_ETH.json").write_text("{}", encoding="utf-8")
    out = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: out.append(" ".join(map(str, a))))
    M.main([str(tmp_path / "snap_ETH.json")])
    assert not [x for x in out if x.startswith("ALERT")]  # first miss: recorded in monitor.json, no e-mail
    assert json.loads((tmp_path / "monitor.json").read_text())["assets"]["ETH"]["problems"]
    M.main([str(tmp_path / "snap_ETH.json")])
    assert [x for x in out if x.startswith("ALERT ETH: server unreachable")]
