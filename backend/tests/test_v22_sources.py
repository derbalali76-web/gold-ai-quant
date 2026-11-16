"""v1.14: per-source freshness on every decision; week/month analysis refused on stale daily candles."""
import numpy as np
import pandas as pd

from goldquant import outlook as OL
from goldquant import source_status as SS


def _bars(end, n, minutes):
    idx = pd.date_range(end=end, periods=n, freq=f"{minutes}min", tz="UTC")
    c = 2000 + np.cumsum(np.random.default_rng(1).normal(0, 1, n))
    return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c}, index=idx)


def test_states_ok_stale_closed_down():
    now = pd.Timestamp("2026-11-18 12:07", tz="UTC")  # Wednesday
    bars = {"M15": _bars("2026-11-18 11:45", 50, 15),            # closed 12:00: 7 min old
            "H4": _bars("2026-11-17 16:00", 50, 240)}            # closed 17 Nov 20:00: 16 h old > 10 h
    out = {s.source: s for s in SS.build(now.to_pydatetime(), now - pd.Timedelta(minutes=1), bars)}
    assert out["PRICE"].state == "OK" and out["M15"].state == "OK" and out["H4"].state == "STALE"
    assert out["H4"].last_update_utc == pd.Timestamp("2026-11-17 20:00", tz="UTC")
    assert SS.build(now.to_pydatetime(), None)[0].state == "DOWN"
    sat = pd.Timestamp("2026-11-21 10:00", tz="UTC")  # market closed: Friday's last bars are not "late"
    fri = {"M15": _bars("2026-11-20 21:45", 50, 15)}
    s = {x.source: x for x in SS.build(sat.to_pydatetime(), pd.Timestamp("2026-11-20 22:00", tz="UTC"), fri,
                                         market_closed=True)}
    assert s["PRICE"].state == "CLOSED" and s["M15"].state == "CLOSED"


def test_monday_morning_is_not_stale_for_gold_but_is_for_crypto():
    mon = pd.Timestamp("2026-11-16 06:00", tz="UTC")
    h1 = {"H1": _bars("2026-11-16 04:00", 50, 60)}  # closed 05:00
    assert {x.source: x.state for x in SS.build(mon.to_pydatetime(), mon, h1)}["H1"] == "OK"
    fri = {"H1": _bars("2026-11-13 20:00", 50, 60)}  # Friday 21:00 close: ~7 h of trading for gold
    assert {x.source: x.state for x in SS.build(mon.to_pydatetime(), mon, fri)}["H1"] == "STALE"
    assert {x.source: x.state for x in SS.build(mon.to_pydatetime(), mon, fri, gold_hours=False)}["H1"] == "STALE"


def _daily(last_open, n=700):
    idx = pd.date_range(end=last_open, periods=n, freq="D", tz="UTC")
    c = 2000 + np.cumsum(np.random.default_rng(2).normal(0, 10, n))
    return pd.DataFrame({"open": c, "high": c + 5, "low": c - 5, "close": c}, index=idx)


def test_outlook_refuses_stale_daily_candles():
    now = pd.Timestamp("2026-11-18 12:00", tz="UTC")
    fresh = OL.compute(_daily("2026-11-17"), now.to_pydatetime())
    assert all(v.action != "UNAVAILABLE" for v in fresh)
    old = OL.compute(_daily("2026-11-12"), now.to_pydatetime())  # source stalled for days
    assert all(v.action == "UNAVAILABLE" and v.reason_msg.code == "va.daily_stale" for v in old)
    assert "2026-11-12" in old[0].reason_ar
    mon = pd.Timestamp("2026-11-16 08:00", tz="UTC")  # Friday's bar is the latest after a weekend: not stale
    assert all(v.action != "UNAVAILABLE" for v in OL.compute(_daily("2026-11-13"), mon.to_pydatetime()))
    assert all(v.action == "UNAVAILABLE"
               for v in OL.compute(_daily("2026-11-13"), mon.to_pydatetime(), gold_hours=False))


def test_crypto_decision_lists_its_sources():
    from goldquant import crypto_engine as CE
    from tests.test_v18_calendar_state import NOW, ev, svc
    rng = np.random.default_rng(3)

    class Feed:
        def bars(self, sym, tf, as_of, limit=1000):
            m = {"M15": 15, "M30": 30, "H1": 60, "H4": 240, "1d": 1440}[tf]
            idx = pd.date_range(end=pd.Timestamp(NOW).floor(f"{m}min") - pd.Timedelta(minutes=m), periods=800,
                                freq=f"{m}min", tz="UTC")
            c = 90000 * np.exp(np.cumsum(rng.normal(0, 0.002, len(idx))))
            o = np.r_[c[0], c[:-1]]
            return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999,
                                 "close": c, "volume": 1.0, "tick_volume": 1.0, "taker_buy_volume": 0.5}, index=idx)
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp())
    d = CE.decide("BTC", Feed(), NOW, ctx=svc(tmp, events=[ev(24 * 5)]).snapshot(NOW))
    got = {s.source: s.state for s in d.sources}
    assert {"PRICE", "M15", "H1", "H4", "D1", "CALENDAR"} <= set(got) and got["PRICE"] == "OK"
    assert got["CALENDAR"] == "OK"
    assert "sources" in d.model_dump(mode="json")


def test_gold_demo_decision_lists_its_sources():
    from fastapi.testclient import TestClient
    from goldquant.api import create_app
    r = TestClient(create_app(":memory:")).get("/decision", params={"mode": "DEMO"}).json()
    names = {s["source"] for s in r["sources"]}
    assert {"PRICE", "M15", "H1", "H4"} <= names


# ---------------- "update" push when the price enters a support / resistance zone
def _lv(name, price, w=3.0):
    from types import SimpleNamespace as NS
    return NS(name=name, price=price, zone_low=price - w, zone_high=price + w)


def _zdec(q):
    from types import SimpleNamespace as NS
    levels = NS(supports=[_lv("S1", 3855), _lv("S2", 3832)], resistances=[_lv("R1", 3891), _lv("R2", 3911)])
    return NS(quote=q, market_closed=False, levels=levels, daily_brief=NS(events=[]),
              outlooks=[NS(horizon="HOURS", plan=None)])


def test_zone_update_text_parts():
    from goldquant.push import zone_update
    assert zone_update(_zdec(3871)) is None  # between zones: nothing
    z = zone_update(_zdec(3856))
    assert z["side"] == "SUPPORT" and (z["low"], z["high"], z["next"], z["other"]) == (3852, 3858, 3832, 3891)
    r = zone_update(_zdec(3890))
    assert r["side"] == "RESISTANCE" and (r["next"], r["other"]) == (3911, 3855)
    assert zone_update(_zdec(3833)) is None  # S2 has no further level: no half message


def test_zone_push_once_per_zone_and_capped(tmp_path):
    import json as _j
    from goldquant.push import PushService
    sent = []
    s = PushService(tmp_path, creds_json=_j.dumps({"project_id": "t"}), sender=lambda t, p: (sent.append(p["message"]["data"]), True)[1])
    s.register("f" * 40, ["XAU"], [], "ar")
    assert s.tick(lambda a: _zdec(3856), force=True)["sent"] == 1 and sent[-1]["type"] == "zone"
    assert s.tick(lambda a: _zdec(3855), force=True)["sent"] == 0  # same zone, same day
    assert s.tick(lambda a: _zdec(3890), force=True)["sent"] == 1  # another zone
    closed = _zdec(3856); closed.market_closed = True
    s2 = PushService(tmp_path / "b", creds_json=_j.dumps({"project_id": "t"}), sender=lambda t, p: True)
    s2.register("g" * 40, ["XAU"], [], "ar")
    assert s2.tick(lambda a: closed, force=True)["sent"] == 0


# ---------------- first touch: descriptive history of which level is reached first
def _walk(n=6000, seed=4):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    c = 2000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.0008, "low": np.minimum(o, c) * 0.9992, "close": c},
                        index=idx)


def test_first_touch_reflects_distance_and_is_checked_out_of_sample():
    from goldquant import brief as BR
    t = BR.first_touch_table(_walk())
    near_dn = t["cells"]["0.5|3.0"]  # lower level much closer
    near_up = t["cells"]["3.0|0.5"]
    assert near_dn[0] > 0.75 and near_up[0] < 0.25  # random walk: the closer level is usually first
    assert all(len(v) == 5 for v in t["cells"].values())
    usable = [v for v in t["cells"].values() if v[4]]
    assert usable and all(v[1] >= BR.FT_MIN_N and v[3] >= BR.FT_MIN_N_HOLD for v in usable)


def test_attach_first_touch_only_from_usable_cells():
    from goldquant import brief as BR
    from goldquant.schemas import DailyBrief, Scenario
    b = DailyBrief(date="2026-11-16", bias="DOWN", price=3863.0,
                   scenarios=[Scenario(kind="BEAR", trigger=3853.27, trigger_level="S1"),
                              Scenario(kind="BULL", trigger=3884.65, trigger_level="R1")])
    table = {"first_touch": {"window_hours": 48, "days": 728,
                             "cells": {"1.0|2.0": [0.66, 900, 0.64, 180, True], "1.0|1.5": [0.6, 50, 0.5, 9, False]}}}
    BR.attach_first_touch(b, table, 3863.0, 3853.27, 3884.65, 10.0)  # a = 0.97 ATR, b = 2.17 ATR
    assert b.first_touch.down_first == 0.66 and b.first_touch.up_first == 0.34 and b.first_touch.n == 900
    b2 = b.model_copy(update={"first_touch": None})
    BR.attach_first_touch(b2, table, 3863.0, 3853.27, 3878.0, 10.0)  # b = 1.5: cell not usable -> nothing
    assert b2.first_touch is None
    BR.attach_first_touch(b2, table, 3863.0, 3853.27, 3884.65, None)
    assert b2.first_touch is None
