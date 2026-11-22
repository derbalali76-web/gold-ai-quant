"""decision-state-2 view/radar: owner rules approved 2026-11-22 (phase 4)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ledger"))
import decision_state as D  # noqa: E402

NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
PRICE = {"value": 100.0, "at": D.iso(NOW - timedelta(minutes=30))}


def adv(h, c, asset="BTC", at=95.0, ex=102.0, exp_h=60):
    return {"asset": asset, "date": "2026-11-22", "version": "advice-0.1.0", "recorded_at": D.iso(NOW - timedelta(hours=2)),
            "expires": D.iso(NOW + timedelta(hours=exp_h)),
            "hold": {"advice": h, "at": at, "exit": ex}, "cash": {"advice": c, "at": at, "exit": 108.0},
            "hours": {"likely": "DOWN", "down": [97.0, 94.0], "up": [104.0]}, "week": {"likely": "UP"}}


def st(asset, side, a, verdict="PASS"):
    return {"assets": {asset: {side: {a: {"n": 25, "verdict": verdict}}}}}


def both(*ss):
    out = {"assets": {}}
    for s in ss:
        for a, x in s["assets"].items():
            for side, y in x.items():
                out["assets"].setdefault(a, {}).setdefault(side, {}).update(y)
    return out


def consistent(s):
    v, r = s["view"], s["radar"]
    q_ids = {i["id"] for i in r if i["state"] == "QUALIFIED"}
    exec_ids = {v[k]["signal_id"] for k in ("holder", "cash") if v[k]["verdict"] != "WAIT"}
    return q_ids == exec_ids


ALL_H = list(D.HOLD_MAP)
ALL_C = list(D.CASH_MAP)


def test_scenario_alone_never_gives_buy_or_sell():
    for h in ALL_H:
        for c in ALL_C:
            s = D.build("BTC", adv(h, c), {}, PRICE, None, NOW)
            assert s["view"]["holder"]["verdict"] == "WAIT" and s["view"]["cash"]["verdict"] == "WAIT"
            assert s["view"]["holder"]["why"] and s["view"]["cash"]["why"]
            assert s["scenario"] is not None and s["scenario"]["stage"] == "FORECAST"   # scenario still shown
            assert consistent(s)


def test_qualified_preemptive_sell_for_holder_has_full_plan():
    s = D.build("BTC", adv("SELL_NOW", "WAIT_BUY_LOWER"), st("BTC", "hold", "SELL_NOW"), PRICE, None, NOW)
    h = s["view"]["holder"]
    assert h["verdict"] == "SELL_THEN_REBUY"
    assert h["plan"] == {"sell": 100.0, "rebuy_at": 95.0, "invalidate_above": 102.0, "duration_h": 60, "adaptive": True}
    assert h["plan"]["sell"] > s["scenario"]["hours"]["down"][0]          # sold before the support breaks
    assert s["view"]["cash"]["verdict"] == "WAIT"
    assert consistent(s) and [i["state"] for i in s["radar"]] == ["QUALIFIED"]


def test_cash_never_sells_and_qualified_buy_has_entry_target_invalidation_duration():
    for h in ALL_H:
        for c in ALL_C:
            for stats in ({}, st("ETH", "cash", c), st("ETH", "hold", h), both(st("ETH", "cash", c), st("ETH", "hold", h))):
                s = D.build("ETH", adv(h, c, asset="ETH"), stats, PRICE, None, NOW)
                assert s["view"]["cash"]["verdict"] in ("BUY", "BUY_LIMIT", "WAIT")
                assert consistent(s)
    s = D.build("ETH", adv("NOTHING", "BUY_NOW", asset="ETH"), st("ETH", "cash", "BUY_NOW"), PRICE, None, NOW)
    p = s["view"]["cash"]["plan"]
    assert s["view"]["cash"]["verdict"] == "BUY" and p["entry"] == 100.0 and p["target"] == 108.0
    assert p["invalidate_below"] == 97.0 and p["duration_h"] == 60
    s = D.build("ETH", adv("NOTHING", "WAIT_BUY_LOWER", asset="ETH"), st("ETH", "cash", "WAIT_BUY_LOWER"), PRICE, None, NOW)
    assert s["view"]["cash"]["verdict"] == "BUY_LIMIT" and s["view"]["cash"]["plan"]["entry"] == 95.0


def test_adaptive_duration_can_exceed_24h():
    s = D.build("BTC", adv("SELL_NOW", "NOTHING", exp_h=150), st("BTC", "hold", "SELL_NOW"), PRICE, None, NOW)
    assert s["view"]["holder"]["plan"]["duration_h"] == 150


def test_failed_record_and_gates_give_wait_with_reasons():
    s = D.build("BTC", adv("SELL_NOW", "NOTHING"), st("BTC", "hold", "SELL_NOW", "FAIL"), PRICE, None, NOW)
    assert s["view"]["holder"] ["verdict"] == "WAIT" and s["view"]["holder"]["why"] == ["record_failed"]
    assert [i["state"] for i in s["radar"]] == ["REJECTED"] and consistent(s)
    stale = {"value": 100.0, "at": D.iso(NOW - timedelta(hours=5))}
    s = D.build("BTC", adv("SELL_NOW", "NOTHING"), st("BTC", "hold", "SELL_NOW"), stale, None, NOW)
    assert s["view"]["holder"]["verdict"] == "WAIT" and s["view"]["holder"]["why"][0].startswith("blocked:")
    assert not any(i["state"] == "QUALIFIED" for i in s["radar"])


def test_price_only_asset():
    s = D.build("PAXG", None, {}, PRICE, None, NOW)
    assert s["view"]["holder"]["why"] == ["price_only_asset"] and s["radar"] == []


def test_te_live_is_forming_paper_test_never_qualified():
    te = {"engine": "te-live-h1-0.1", "asset": "BTC", "active": [{"seq": 7, "limit": 99.0, "stop": 97.0, "target": 99.7, "status": "PENDING"}],
          "last_closed": {"seq": 6, "status": "NOT_FILLED"}, "record": {}}
    s = D.build("BTC", adv("NOTHING", "NOTHING"), {}, PRICE, te, NOW)
    states = {i["id"]: (i["state"], i.get("stage")) for i in s["radar"]}
    assert states == {"te-7": ("FORMING", "PAPER_TEST"), "te-6": ("EXPIRED", "PAPER_TEST")}
    assert s["view"]["cash"]["verdict"] == "WAIT"
