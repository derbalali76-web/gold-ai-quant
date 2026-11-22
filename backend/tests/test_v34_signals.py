"""signals-1: append-only life cycle, no silent edits, no double issue, restart rebuild, honest statistics."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ledger"))
import signals as S  # noqa: E402


def sig(i="s1", **kw):
    d = {"id": i, "asset": "BTC", "kind": "BUY", "strategy": "demo", "rules_version": "demo-0.1", "issued_at": "2026-11-22T12:00:00Z",
         "ref_price": 100.0, "trigger": "limit", "entry": 99.0, "target": 103.0, "stop": 97.0,
         "expires_at": "2026-11-23T00:00:00Z", "costs": {"maker": 0.001}, "data_source": "binance 15m"}
    d.update(kw)
    return d


def test_issue_once_and_rebuild_after_restart(tmp_path):
    p = tmp_path / "b.jsonl"
    b = S.Book(p)
    assert b.issue(sig(), "2026-11-22T12:00:05Z") and not b.issue(sig(), "2026-11-22T12:01:00Z")
    b.update("s1", "ACTIVATE", {"fill": 99.0, "at": "2026-11-22T13:00:00Z"}, "2026-11-22T13:01:00Z")
    b2 = S.Book(p)                                                   # a restart reads the same state
    assert b2.state("s1")["status"] == "ACTIVE" and len(b2.lines) == 2


def test_history_is_never_rewritten_and_edits_are_detected(tmp_path):
    p = tmp_path / "b.jsonl"
    b = S.Book(p)
    b.issue(sig(), "t0")
    b.update("s1", "ACTIVATE", {"fill": 99.0, "at": "t1"}, "t1")
    b.update("s1", "CLOSE", {"status": "STOP", "exit": 97.0, "net": -0.022, "at": "t2"}, "t2")
    with pytest.raises(S.SignalError):
        b.update("s1", "CLOSE", {"status": "TARGET", "exit": 103.0, "net": 0.04, "at": "t3"}, "t3")
    p.write_text(p.read_text().replace('"STOP"', '"TARGET"'))
    with pytest.raises(S.SignalError):
        S.Book(p)


def test_level_changes_are_new_decisions_and_losers_are_not_extended(tmp_path):
    b = S.Book(tmp_path / "b.jsonl")
    b.issue(sig(), "t0")
    b.update("s1", "ACTIVATE", {"fill": 99.0, "at": "t1"}, "t1")
    with pytest.raises(S.SignalError):
        b.update("s1", "EXTEND_TARGET", {"target": 106.0}, "t2")                      # no rule / reason
    with pytest.raises(S.SignalError):
        b.update("s1", "EXTEND_TARGET", {"target": 106.0, "rule_version": "r1", "reason": "x", "price": 98.0}, "t2")
    with pytest.raises(S.SignalError):
        b.update("s1", "MOVE_STOP", {"stop": 95.0, "rule_version": "r1", "reason": "x"}, "t2")   # widening
    b.update("s1", "EXTEND_TARGET", {"target": 106.0, "rule_version": "r1", "reason": "trend held", "price": 102.5}, "t2")
    s = b.state("s1")
    assert s["target"] == 106.0 and s["original"]["target"] == 103.0 and s["history"][-1]["kind"] == "EXTEND_TARGET"


def test_untriggered_and_cancelled_are_not_wins_or_losses(tmp_path):
    b = S.Book(tmp_path / "b.jsonl")
    for i in ("a", "b", "c", "d"):
        b.issue(sig(i), "t0")
    b.update("a", "CLOSE", {"status": "EXPIRED_UNTRIGGERED", "at": "t1"}, "t1")
    b.update("b", "CANCEL", {"reason": "conditions changed"}, "t1")
    b.update("c", "ACTIVATE", {"fill": 99.0, "at": "t1"}, "t1")
    b.update("c", "CLOSE", {"status": "TIME_EXIT", "exit": 99.5, "net": 0.003, "at": "t2"}, "t2")
    with pytest.raises(S.SignalError):
        b.update("d", "CLOSE", {"status": "TARGET", "net": 0.04, "at": "t2"}, "t2")   # never activated
    st = b.stats()
    assert st["activated_closed"] == 1 and st["wins"] == 1 and st["losses"] == 0
    assert st["expired_untriggered"] == 1 and st["cancelled"] == 1 and st["pending"] == 1


def test_forecasts_are_rejected_and_bad_geometry_too(tmp_path):
    b = S.Book(tmp_path / "b.jsonl")
    with pytest.raises(S.SignalError):
        b.issue(sig(), "t0", layer="FORECAST")
    with pytest.raises(S.SignalError):
        b.issue(sig(stop=100.0), "t0")
    with pytest.raises(S.SignalError):
        b.issue({"id": "x"}, "t0")
    assert S.TE_MAP["NOT_FILLED"] == "EXPIRED_UNTRIGGERED" and S.TE_MAP["NO_DATA"] == "DATA_INVALID"
