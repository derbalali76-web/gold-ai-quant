"""decision-state-1: one market signal, personalised actions, evidence stages, price-only assets, durable record."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ledger"))
import decision_state as D  # noqa: E402

NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
PRICE = {"value": 100.0, "at": D.iso(NOW - timedelta(minutes=30))}


def adv(h, c, at=95.0, ex=102.0, asset="BTC", age_h=2):
    return {"asset": asset, "date": "2026-11-22", "version": "advice-0.1.0", "recorded_at": D.iso(NOW - timedelta(hours=age_h)),
            "hold": {"advice": h, "at": at, "exit": ex}, "cash": {"advice": c, "at": at, "exit": ex},
            "hours": {"likely": "DOWN"}, "week": {"likely": "UP"}}


def stats(asset, side, a, verdict):
    return {"assets": {asset: {side: {a: {"n": 25, "verdict": verdict}}}}}


ACTIONS_HOLDER = {"SELL_OWNED", "HOLD", "WAIT"}
ACTIONS_CASH = {"BUY", "WAIT"}


def test_preemptive_sell_is_allowed_and_labelled_as_scenario():
    s = D.build("BTC", adv("SELL_NOW", "WAIT_BUY_LOWER"), {}, PRICE, None, NOW)
    h, c = s["actions"]["holder"], s["actions"]["cash"]
    assert h["action"] == "SELL_OWNED" and h["rebuy_at"] == 95.0 and h["stage"] == "SCENARIO"
    assert c["action"] == "WAIT" and c["level"] == 95.0
    assert s["signal"]["kind"] == "DOWN_MOVE" and s["actions"]["signal_id"] == s["signal"]["id"]


def test_owner_never_short_or_buy_cash_never_sells_owned():
    combos = [(h, c) for h in D.HOLD_MAP for c in D.CASH_MAP]
    for h, c in combos:
        a = D.build("ETH", adv(h, c, asset="ETH"), {}, PRICE, None, NOW)["actions"]
        assert a["holder"]["action"] in ACTIONS_HOLDER and a["holder"]["action"] != "BUY"
        assert a["cash"]["action"] in ACTIONS_CASH


def test_no_contradictory_recommendations_for_one_signal():
    for h, c in [(h, c) for h in D.HOLD_MAP for c in D.CASH_MAP]:
        a = D.build("SOL", adv(h, c, asset="SOL"), {}, PRICE, None, NOW)["actions"]
        assert not (a["holder"]["action"] == "SELL_OWNED" and a["cash"]["action"] == "BUY")
    s = D.build("SOL", adv("SELL_NOW", "BUY_NOW", asset="SOL"), {}, PRICE, None, NOW)
    assert s["signal"]["kind"] == "CONFLICT" and s["actions"]["holder"]["stage"] == "BLOCKED"


def test_failed_gate_issues_no_trade():
    stale_price = {"value": 100.0, "at": D.iso(NOW - timedelta(hours=5))}
    for p, a in ((stale_price, adv("SELL_NOW", "WAIT_BUY_LOWER")), (PRICE, adv("KEEP_SELL_HIGHER", "BUY_NOW", age_h=40)), (None, adv("SELL_NOW", "WAIT_BUY_LOWER"))):
        s = D.build("BTC", a, {}, p, None, NOW)
        assert s["actions"]["holder"]["action"] in ("HOLD",) and s["actions"]["cash"]["action"] == "WAIT"
        assert not s["gates"]["ok"]


def test_only_a_passed_record_qualifies_and_a_failed_one_is_not_recommended():
    a = adv("SELL_NOW", "WAIT_BUY_LOWER")
    assert D.build("BTC", a, stats("BTC", "hold", "SELL_NOW", None), PRICE, None, NOW)["actions"]["holder"]["stage"] == "SCENARIO"
    q = D.build("BTC", a, stats("BTC", "hold", "SELL_NOW", "PASS"), PRICE, None, NOW)["actions"]["holder"]
    assert q["stage"] == "QUALIFIED" and q["action"] == "SELL_OWNED"
    f = D.build("BTC", a, stats("BTC", "hold", "SELL_NOW", "FAIL"), PRICE, None, NOW)["actions"]["holder"]
    assert f["stage"] == "FAILED" and f["action"] == "HOLD"


def test_paxg_is_price_only_and_te_is_paper_test():
    s = D.build("PAXG", adv("SELL_NOW", "WAIT_BUY_LOWER", asset="PAXG"), {}, PRICE, None, NOW)
    assert s["actions"]["holder"]["action"] == "HOLD" and s["actions"]["holder"]["reason"] == "price_only_asset" and s["signal"] is None
    te = {"asset": "BTC", "engine": "te-live-h1-0.1", "active": [{"seq": 3}], "record": {"orders": 1}}
    o = D.build("BTC", None, {}, PRICE, te, NOW)["opportunity"]
    assert o["stage"] == "PAPER_TEST" and o["active"]["seq"] == 3


def test_apply_records_only_changes_and_survives_restart(tmp_path):
    rec = lambda seq, a: json.dumps({"seq": seq, "kind": "ADVICE", "recorded_at": a["recorded_at"], "data": a})
    (tmp_path / "ledger.jsonl").write_text(rec(1, adv("SELL_NOW", "WAIT_BUY_LOWER")) + "\n")
    (tmp_path / "bars_BTC_H1.json").write_text(json.dumps([[D.iso(NOW - timedelta(hours=1)), 1, 1, 1, 100.0]]))
    ind = tmp_path / "in"; ind.mkdir()
    (ind / "prices.json").write_text(json.dumps({"PAXG": {"value": 2650.0, "at": D.iso(NOW)}}))
    o = D.apply(ind, tmp_path, NOW)
    n1 = len(D.chain_lines(tmp_path))
    assert n1 == 5 and o["assets"]["PAXG"]["price"]["value"] == 2650.0           # one STATE per asset at first
    D.apply(ind, tmp_path, NOW + timedelta(minutes=30))                           # nothing changed: nothing written
    assert len(D.chain_lines(tmp_path)) == n1 and D.verify(tmp_path)
    (tmp_path / "ledger.jsonl").write_text(rec(1, adv("SELL_NOW", "WAIT_BUY_LOWER")) + "\n" + rec(2, adv("NOTHING", "NOTHING")) + "\n")
    D.apply(ind, tmp_path, NOW + timedelta(hours=1))
    assert len(D.chain_lines(tmp_path)) == n1 + 1 and D.verify(tmp_path)          # only BTC changed
    lines = (tmp_path / "decision" / "states.jsonl").read_text().splitlines()
    (tmp_path / "decision" / "states.jsonl").write_text("\n".join(lines[:-1] + [lines[-1].replace("HOLD", "BUY")]) + "\n")
    assert not D.verify(tmp_path)                                                 # a silent edit is detected
