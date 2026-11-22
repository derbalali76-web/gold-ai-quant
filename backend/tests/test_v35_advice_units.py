"""advice-units-0.1: pre-emptive sell vs hold vs sell-after-break, in units after fees."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ledger"))
import advice_units as U  # noqa: E402

REC = {"hold": {"advice": "SELL_NOW", "at": 90.0, "exit": 106.0}, "hours": {"down": [95.0, 88.0]},
       "price_at_record": 100.0, "cost": 0.2}


def bar(o, h, l, c, t="t"):
    return [t, o, h, l, c]


def test_preemptive_wins_when_price_falls_to_rebuy():
    w = [bar(100, 100, 97, 97), bar(97, 97, 94, 94), bar(94, 94, 89, 91), bar(91, 93, 90, 92)]
    r = U.score(REC, w)
    pe, ab = r["pre_emptive"], r["after_break"]
    assert pe["how"] == "BOUGHT_BACK" and pe["units"] == round((100 - 0.1) / (90 + 0.1), 6) and pe["gain_pct"] > 10
    assert ab["sold_at"] == 94 and ab["how"] == "BOUGHT_BACK"            # sold after the close below 95
    assert pe["units"] > ab["units"] > 1.0 and not pe["rose_no_return"]


def test_rose_and_never_returned_is_flagged_and_protection_limits_it():
    w = [bar(100, 103, 99, 102), bar(102, 105, 101, 104), bar(104, 105, 103, 104)]
    r = U.score(REC, w)
    pe = r["pre_emptive"]
    assert pe["how"] == "NO_REBUY" and pe["rose_no_return"] and pe["gain_pct"] < 0
    assert r["after_break"]["how"] == "NO_BREAK" and r["after_break"]["units"] == 1.0
    w2 = w + [bar(104, 107, 104, 107)]                                     # protection above 106
    pe2 = U.score(REC, w2)["pre_emptive"]
    assert pe2["how"] == "PROTECTION" and pe2["price"] == 106 and pe2["units"] < 1.0


def test_both_levels_in_one_bar_take_the_worse_case_and_gaps_fill_at_open():
    w = [bar(100, 107, 89, 100)]
    assert U.score(REC, w)["pre_emptive"]["how"] == "PROTECTION"
    w = [bar(100, 100, 98, 98), bar(85, 86, 84, 85)]                       # gap below the buy-back level
    pe = U.score(REC, w)["pre_emptive"]
    assert pe["how"] == "BOUGHT_BACK" and pe["price"] == 85


def test_only_sell_now_with_a_support_is_studied_and_verdict_needs_20():
    assert U.score(dict(REC, hold={"advice": "NOTHING"}), [bar(1, 1, 1, 1)]) is None
    assert U.score(dict(REC, hours={"down": None}), [bar(1, 1, 1, 1)]) is None
    w = [bar(100, 100, 89, 91)]
    rows = [{"date": f"2026-11-{d:02d}", "asset": "BTC", "result": U.score(REC, w)} for d in range(1, 11)]
    s = U.stats(rows)
    assert s["n"] == 10 and "verdict" not in s["pre_emptive"] and s["independent_weeks"] == 2
    rows = [{"date": f"2026-{m:02d}-01", "asset": "BTC", "result": U.score(REC, w)} for m in range(1, 13)] * 2
    s = U.stats(rows)
    assert s["pre_emptive"]["verdict"] == "USEFUL" and s["pre_emptive"]["no_rebuy"] == 0


def test_runner_scores_once_after_the_window(tmp_path):
    import json
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 11, 10, 0, tzinfo=timezone.utc)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    adv = dict(REC, asset="BTC", date="2026-11-10", expires=iso(t0 + timedelta(hours=168)))
    other = dict(adv, hold={"advice": "NOTHING"}, date="2026-11-11")
    (tmp_path / "ledger.jsonl").write_text("\n".join(json.dumps({"seq": i, "kind": "ADVICE", "recorded_at": iso(t0), "data": a})
                                                     for i, a in ((5, adv), (6, other))) + "\n")
    bars = [[iso(t0 + timedelta(hours=k)), 100 - k * 0.1, 100 - k * 0.1, 99 - k * 0.1, 99.5 - k * 0.1] for k in range(200)]
    (tmp_path / "bars_BTC_H1.json").write_text(json.dumps(bars))
    assert U.run(tmp_path, t0 + timedelta(hours=100))["n"] == 0             # window not complete yet
    s = U.run(tmp_path, t0 + timedelta(hours=170))
    assert s["n"] == 1 and s["pre_emptive"]["mean_gain_pct"] > 0
    U.run(tmp_path, t0 + timedelta(hours=171))
    assert len((tmp_path / "studies" / "advice_units.jsonl").read_text().splitlines()) == 1
