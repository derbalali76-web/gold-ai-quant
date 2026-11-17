"""advice-0.1.0: the app's «ماذا أفعل؟» mirrored in the ledger, recorded before outcomes and scored conservatively.
The decision cases are the same as android HorizonScenariosTest (same levels, same expected instructions)."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "ledger" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


A = _load("advice")
L = _load("ledger")
T0 = datetime(2026, 11, 16, 9, 30, tzinfo=timezone.utc)


def snap(hours_action="WAIT", week_action="WAIT", brief=None, outcome3=None, plan_hours=None, price=72.0, now=T0):
    b = brief
    if outcome3 is not None:
        b = dict(b or {}, outcome3=outcome3)
    return {"as_of": L.iso(now), "symbol": "SOLUSDT", "asset": "SOL", "price": price, "cost": 0.2, "mode": "LIVE",
            "market_closed": False, "model_version": "m1", "recommendations": [], "brief": b, "action": hours_action,
            "bars": {"H1": [], "D1": []},
            "outlooks": [{"horizon": "HOURS", "action": hours_action, "plan_side": plan_hours,
                          "supports": [70.0, 69.0], "resistances": [74.0, 75.0]},
                         {"horizon": "WEEK", "action": week_action, "plan_side": None,
                          "supports": [64.0, 58.0], "resistances": [80.0, 88.0]},
                         {"horizon": "MONTH", "action": "WAIT", "plan_side": None, "supports": [], "resistances": []}]}


def dec(s, hold):
    return A.decide(A.view(s, "HOURS"), A.view(s, "WEEK"), hold)


def P(advice, at, exit_, mix, basis):
    return {"advice": advice, "at": at, "exit": exit_, "mix": mix, "basis": basis}


def test_single_horizon_cases_match_the_app():
    assert dec(snap("SELL"), True) == P("SELL_NOW", 69.0, 74.0, None, "HOURS")
    assert dec(snap("SELL"), False) == P("WAIT_BUY_LOWER", 69.0, 74.0, None, "HOURS")
    assert dec(snap("BUY"), True) == P("KEEP_SELL_HIGHER", 75.0, 70.0, None, "HOURS")
    assert dec(snap("BUY"), False) == P("BUY_NOW", None, 70.0, None, "HOURS")
    assert dec(snap("SELL", "SELL"), True) == P("SELL_NOW", 69.0, 74.0, None, "HOURS")
    assert dec(snap("WAIT", "BUY"), True) == P("KEEP_SELL_HIGHER", 88.0, 64.0, None, "WEEK")
    assert dec(snap("WAIT", "SELL"), False) == P("WAIT_BUY_LOWER", 58.0, 80.0, None, "WEEK")
    assert dec(snap(), True)["advice"] == "NOTHING"


def test_mixed_horizons_match_the_app():
    assert dec(snap("SELL", "BUY"), True) == P("SELL_NOW", 69.0, 74.0, "DIP_IN_UPTREND", "HOURS")
    assert dec(snap("SELL", "BUY"), False) == P("WAIT_BUY_LOWER", 69.0, 74.0, "DIP_IN_UPTREND", "HOURS")
    assert dec(snap("BUY", "SELL"), True) == P("KEEP_SELL_HIGHER", 75.0, 70.0, "BOUNCE_IN_DOWNTREND", "HOURS")
    assert dec(snap("BUY", "SELL"), False) == P("DONT_BUY", None, None, "BOUNCE_IN_DOWNTREND", "HOURS")


def test_evidence_order_and_brief_levels():
    brief = {"scenarios": [{"kind": "BEAR", "trigger": 70.5, "target": 68.0}, {"kind": "BULL", "trigger": 73.5, "target": 76.0}]}
    o3 = {"down_level": 70.5, "up_level": 73.5, "likely": "DOWN"}
    v = A.view(snap(brief=brief, outcome3=o3), "HOURS")
    assert v == {"down": [70.5, 68.0], "up": [73.5, 76.0], "likely": "DOWN"}  # brief levels win for HOURS
    assert A.view(snap(brief=brief, outcome3=dict(o3, likely="NONE")), "HOURS")["likely"] == "BETWEEN"
    assert A.view(snap(brief=brief, outcome3=dict(o3, down_level=69.0)), "HOURS")["likely"] == "NONE"  # other levels
    assert A.view(snap("SELL", plan_hours="BUY"), "HOURS")["likely"] == "UP"  # a validated plan wins
    demo = snap("SELL", plan_hours="BUY")
    demo["mode"] = "DEMO"
    assert A.view(demo, "HOURS")["likely"] == "DOWN"
    between = snap(brief=brief, outcome3=dict(o3, likely="NONE"), week_action="BUY")
    assert dec(between, True)["basis"] == "WEEK"


def bar(t, o, h, l, c):
    return (t, o, h, l, c)


def win(rows):
    return [bar(T0 + timedelta(hours=i + 1), *r) for i, r in enumerate(rows)]


def test_score_sell_now_bought_back_exit_and_never():
    a = {"hold": P("SELL_NOW", 69.0, 74.0, None, "HOURS"), "cash": P("WAIT_BUY_LOWER", 69.0, 74.0, None, "HOURS")}
    r = A.score(a, 72.0, 0.2, win([[72, 72.5, 68.5, 70], [70, 71, 69.5, 71]]))
    assert r["hold"] == {"how": "BOUGHT_BACK", "price": 69.0, "excess_pct": round((72 - 69 - 0.2) / 72 * 100, 4)}
    assert r["cash"] == {"how": "FILLED", "price": 69.0, "return_pct": round((71 - 69 - 0.2) / 72 * 100, 4)}
    # the price rises first: buy back above the exit (a loss against holding)
    r = A.score(a, 72.0, 0.2, win([[72, 74.6, 71.8, 74.4], [74.4, 78, 74, 77]]))
    assert r["hold"]["how"] == "EXIT" and r["hold"]["price"] == 74.0 and r["hold"]["excess_pct"] < 0
    assert r["cash"]["how"] == "EXIT_BUY" and r["cash"]["return_pct"] == round((77 - 74 - 0.2) / 72 * 100, 4)
    # one bar touches both: the worse case (the exit)
    r = A.score(a, 72.0, 0.2, win([[72, 74.5, 68.0, 72]]))
    assert r["hold"]["how"] == "EXIT" and r["cash"]["how"] == "EXIT_BUY"
    # a gap open above the exit fills at the open (worse)
    r = A.score(a, 72.0, 0.2, win([[75, 76, 74.8, 75.5]]))
    assert r["hold"]["price"] == 75
    # never touched: still in cash at the end
    r = A.score(a, 72.0, 0.2, win([[72, 73, 70, 71]]))
    assert r["hold"] == {"how": "NOT_BOUGHT_BACK", "excess_pct": round((72 - 71 - 0.1) / 72 * 100, 4)}
    assert r["cash"] == {"how": "NOT_FILLED", "return_pct": 0.0}
    assert r["ref_buy_hold_pct"] == round((71 - 72 - 0.2) / 72 * 100, 4)


def test_score_keep_sell_higher_buy_now_and_dont_buy():
    a = {"hold": P("KEEP_SELL_HIGHER", 75.0, 70.0, None, "HOURS"), "cash": P("BUY_NOW", None, 70.0, None, "HOURS")}
    r = A.score(a, 72.0, 0.2, win([[72, 75.5, 71.5, 73], [73, 73.5, 71, 72]]))
    assert r["hold"] == {"how": "SOLD", "price": 75.0, "excess_pct": round((75 - 72 - 0.1) / 72 * 100, 4)}
    assert r["cash"] == {"how": "HELD", "price": 72, "return_pct": round((72 - 72 - 0.2) / 72 * 100, 4)}
    r = A.score(a, 72.0, 0.2, win([[72, 72.5, 69.5, 70], [70, 70, 66, 66]]))
    assert r["hold"]["how"] == "EXIT" and r["hold"]["price"] == 70.0
    assert r["hold"]["excess_pct"] == round((70 - 66 - 0.1) / 72 * 100, 4)  # selling saved the fall
    assert r["cash"] == {"how": "EXIT", "price": 70.0, "return_pct": round((70 - 72 - 0.2) / 72 * 100, 4)}
    d = {"hold": P("NOTHING", None, None, None, None), "cash": P("DONT_BUY", None, None, "BOUNCE_IN_DOWNTREND", "HOURS")}
    r = A.score(d, 72.0, 0.2, win([[72, 73, 71, 72]]))
    assert r["hold"]["excess_pct"] == 0.0 and r["cash"] == {"how": "DONT_BUY", "return_pct": 0.0}


def test_stats_verdicts_need_twenty_rows():
    def row(i, hx, cr, ref):
        return {"asset": "SOL", "date": (T0 + timedelta(days=i)).date().isoformat(), "hold_advice": "SELL_NOW",
                "cash_advice": "WAIT_BUY_LOWER", "mix": None,
                "result": {"hold": {"excess_pct": hx}, "cash": {"return_pct": cr}, "ref_buy_hold_pct": ref}}
    s = A.stats([row(i, 1.0, 0.5, 0.1) for i in range(19)])
    assert s["assets"]["SOL"]["hold"]["SELL_NOW"]["verdict"] is None
    s = A.stats([row(i, 1.0 if i % 2 else -0.5, 0.5, 0.1) for i in range(20)])
    h = s["assets"]["SOL"]["hold"]["SELL_NOW"]
    assert h["n"] == 20 and h["win_rate"] == 0.5 and h["mean"] == 0.25 and h["verdict"] == "PASS"
    assert h["weeks"] == 3  # days 0, 7, 14
    c = s["assets"]["SOL"]["cash"]["WAIT_BUY_LOWER"]
    assert c["verdict"] == "PASS" and c["ref_buy_hold_mean"] == 0.1
    s = A.stats([row(i, -0.1, 0.05, 0.1) for i in range(20)])
    assert s["assets"]["SOL"]["hold"]["SELL_NOW"]["verdict"] == "FAIL"
    assert s["assets"]["SOL"]["cash"]["WAIT_BUY_LOWER"]["verdict"] == "FAIL"  # positive but below buy-and-hold


def test_ledger_records_once_a_day_and_scores_after_a_week(tmp_path):
    led = L.Ledger(tmp_path)
    s = snap("SELL", "BUY")
    led.ingest(s, T0)
    led.ingest(snap("BUY", "SELL", now=T0 + timedelta(hours=1)), T0 + timedelta(hours=1))  # same day: not again
    adv = [e for e in led.entries if e["kind"] == "ADVICE"]
    assert len(adv) == 1 and adv[0]["data"]["hold"]["mix"] == "DIP_IN_UPTREND"
    assert adv[0]["data"]["version"] == "advice-0.1.0"
    # bars of the next 168 hours: dips to 68.5 on the first hour, ends at 76
    start = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)
    rows = [[72, 72.2, 68.5, 70]] + [[74, 76.2, 73.8, 76]] * 168
    bars = [[L.iso(start + timedelta(hours=i)), *r] for i, r in enumerate(rows)]
    later = start + timedelta(hours=170)
    s2 = snap(now=later)
    s2["bars"] = {"H1": bars, "D1": []}
    led.ingest(s2, later)
    res = [e for e in led.entries if e["kind"] == "ADVICE_RESULT"]
    assert len(res) == 1 and res[0]["data"]["outcome"] == "SCORED"
    assert res[0]["data"]["hold"]["how"] == "BOUGHT_BACK" and res[0]["data"]["hold"]["price"] == 69.0
    assert L.Ledger(tmp_path).verify() == []
    st = L.stats(led.entries, later)["advice"]
    assert st["recorded"] >= 1 and st["assets"]["SOL"]["hold"]["SELL_NOW"]["n"] == 1


def test_old_snapshots_without_outlooks_record_nothing(tmp_path):
    led = L.Ledger(tmp_path)
    s = snap("SELL")
    del s["outlooks"]
    led.ingest(s, T0)
    assert not [e for e in led.entries if e["kind"] == "ADVICE"]
