import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from goldquant import checklist as CK
from goldquant import context as CX
from goldquant.providers.history import HistoryStore

NOW = datetime(2026, 11, 15, 14, 0, tzinfo=timezone.utc)


def svc(tmp_path, updated=None, events=None, write=True, broken=False):
    p = tmp_path / "calendar_auto.json"
    if write:
        if broken:
            p.write_text("{not json", encoding="utf-8")
        else:
            p.write_text(json.dumps({"updated_at": (updated or NOW).isoformat(), "events": events or []}), encoding="utf-8")
    return CX.ContextService(HistoryStore(":memory:"), tmp_path / "manual.json", auto_calendar_path=p, enabled=False)


def ev(hours, imp=3, name="US CPI"):
    return {"time_utc": (NOW + timedelta(hours=hours)).isoformat(), "name": name, "importance": imp, "source": "bls"}


def test_states_are_distinct(tmp_path):
    a = tmp_path / "a"; a.mkdir()
    assert svc(a, write=False).calendar_status(NOW)["state"] == "NOT_CONFIGURED"
    b = tmp_path / "b"; b.mkdir()
    assert svc(b, broken=True).calendar_status(NOW)["state"] == "DISCONNECTED"
    c = tmp_path / "c"; c.mkdir()
    assert svc(c, updated=NOW - timedelta(days=12), events=[ev(30)]).calendar_status(NOW)["state"] == "STALE"
    d = tmp_path / "d"; d.mkdir()
    st = svc(d, events=[ev(10)]).calendar_status(NOW)
    assert st["state"] == "CONNECTED" and st["updated_at"].startswith("2026-11-15")
    e = tmp_path / "e"; e.mkdir()
    assert svc(e, events=[ev(24 * 5)]).calendar_status(NOW)["state"] == "NO_EVENTS"


def test_unknown_calendar_is_never_no_news(tmp_path):
    from goldquant.schemas import HorizonOutlook
    stale = tmp_path / "s"; stale.mkdir()
    ctx = svc(stale, updated=NOW - timedelta(days=12), events=[ev(30)]).snapshot(NOW)
    assert not CX.news_clear(ctx) and not CX.news_clear(None)
    ok = tmp_path / "o"; ok.mkdir()
    ctx2 = svc(ok, events=[ev(24 * 5)]).snapshot(NOW)
    assert CX.news_clear(ctx2)
    near = tmp_path / "n"; near.mkdir()
    ctx3 = svc(near, events=[ev(0.5)]).snapshot(NOW)
    assert ctx3.embargo_events and not CX.news_clear(ctx3)


def test_crypto_checklist_gets_calendar_and_volatility(tmp_path):
    from goldquant import crypto_engine as CE
    rng = np.random.default_rng(3)

    class Feed:
        def bars(self, sym, tf, as_of, limit=1000):
            m = {"M15": 15, "M30": 30, "H1": 60, "H4": 240, "1d": 1440}[tf]
            idx = pd.date_range(end=pd.Timestamp(NOW).floor(f"{m}min") - pd.Timedelta(minutes=m), periods=800,
                                freq=f"{m}min", tz="UTC")
            c = 90000 * np.exp(np.cumsum(rng.normal(0, 0.002, len(idx))))
            o = np.r_[c[0], c[:-1]]
            return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999,
                                 "close": c, "volume": 1.0 + rng.random(len(idx)), "tick_volume": 1.0,
                                 "taker_buy_volume": 0.5}, index=idx)
    ok = tmp_path / "ok"; ok.mkdir()
    ctx = svc(ok, events=[ev(24 * 5)]).snapshot(NOW)
    d = CE.decide("BTC", Feed(), NOW, ctx=ctx)
    news = next(c for c in d.outlooks[0].checklist if c.code == "news")
    vol = next(c for c in d.outlooks[0].checklist if c.code == "volatility")
    assert news.ok is True and news.state == "NO_EVENTS" and news.updated_at
    assert d.vol_regime is not None and vol.ok is not None
    d2 = CE.decide("BTC", Feed(), NOW, ctx=None)
    n2 = next(c for c in d2.outlooks[0].checklist if c.code == "news")
    assert n2.ok is None and n2.state == "NOT_CONFIGURED"


def test_scenario_history_is_descriptive_and_needs_enough_cases():
    from goldquant import brief as BR
    from goldquant.schemas import DailyBrief, Scenario
    rng = np.random.default_rng(2)
    n = 6000
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    o = np.r_[c[0], c[:-1]]
    h1 = pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.002, "low": np.minimum(o, c) * 0.998, "close": c},
                      index=pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"))
    t = BR.history_table(h1)
    r, k = t["BEAR"]["1.0"]
    assert r is not None and 0 < r < 1 and k >= 30
    few = BR.history_table(h1.iloc[:300])
    assert few["BULL"]["1.0"][0] is None  # too few cases -> nothing shown
    b = DailyBrief(date="2026-11-15", bias="DOWN", price=100.0,
                   scenarios=[Scenario(kind="BEAR", trigger=99.0, trigger_level="S1", target=98.0, target_level="S2")])
    BR.attach_history(b, t, 1.0)
    assert b.scenarios[0].hist_rate == t["BEAR"]["1.0"][0] and b.scenarios[0].hist_n == k
