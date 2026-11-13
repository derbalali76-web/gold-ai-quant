"""v1.7: six setups, watch levels separated from recommendations, honest performance stats."""
import json
from datetime import datetime, timezone

import pytest

from goldquant import paper as PAPER
from goldquant.schemas import Setup, TradePlan


def test_watch_plan_cannot_carry_stop_or_target():
    with pytest.raises(Exception):
        TradePlan(setup=Setup.WAIT_TO_BUY, watch_price=3880.0, stop_loss=3860.0)
    with pytest.raises(Exception):
        TradePlan(setup=Setup.WAIT_TO_SELL)  # needs its watch price
    with pytest.raises(Exception):
        TradePlan(setup=Setup.WAIT, recommendation=True)
    with pytest.raises(Exception):
        TradePlan(setup=Setup.BUY_NOW, entry_low=3900.0)  # missing stop / target
    p = TradePlan(setup=Setup.BUY_NOW, recommendation=True, side="BUY", entry_low=3900, entry_high=3902,
                  stop_loss=3875, target=3950, reward_risk=2.0)
    assert p.recommendation


@pytest.mark.parametrize("fx", ["wait_demo.json", "buy_demo_stub.json", "sell_demo_stub.json",
                                "live_qualified_stub.json", "unavailable_live.json"])
def test_every_horizon_has_a_consistent_plan(fx):
    from pathlib import Path
    d = json.loads((Path(__file__).resolve().parents[2] / "schema" / "fixtures" / fx).read_text(encoding="utf-8"))
    for o in d["outlooks"]:
        p = o["plan"]
        assert p is not None
        if d["mode"] == "DEMO":
            assert not p["recommendation"]  # demo never recommends
        if p["recommendation"]:
            assert p["setup"] in ("BUY_NOW", "SELL_NOW") and o["validated"]
        if o["horizon"] == "HOURS":
            assert (p["setup"] in ("BUY_NOW", "SELL_NOW")) == (d["action"] in ("BUY", "SELL"))
            if d["action"] == "UNAVAILABLE":
                assert p["setup"] == "UNAVAILABLE"
        elif not o["validated"]:
            assert p["setup"] not in ("BUY_NOW", "SELL_NOW")  # unvalidated WEEK/MONTH never become a trade


def test_perf_counts_only_completed_trades():
    rows = [
        {"decision_id": "a", "mode": "LIVE", "opened_at": "2026-11-01T10:00", "status": "CLOSED", "outcome": 1, "pnl": 10.0},
        {"decision_id": "b", "mode": "LIVE", "opened_at": "2026-11-02T10:00", "status": "CLOSED", "outcome": -1, "pnl": -6.0},
        {"decision_id": "c", "mode": "LIVE", "opened_at": "2026-11-03T10:00", "status": "CLOSED", "outcome": -1, "pnl": -5.0},
        {"decision_id": "d", "mode": "LIVE", "opened_at": "2026-11-04T10:00", "status": "NOT_FILLED", "outcome": None, "pnl": 0.0},
        {"decision_id": "e", "mode": "LIVE", "opened_at": "2026-11-05T10:00", "status": "OPEN", "outcome": None, "pnl": None},
        {"decision_id": "f", "mode": "DEMO", "opened_at": "2026-11-05T10:00", "status": "CLOSED", "outcome": 1, "pnl": 99.0},
    ]
    s = PAPER.perf(rows)
    assert (s["trades"], s["hits"], s["pending"], s["not_filled"]) == (3, 1, 1, 1)
    assert s["avg_win"] == 10.0 and s["avg_loss"] == -5.5
    assert s["expectancy"] == pytest.approx(-0.333, abs=1e-3)
    assert s["max_drawdown"] == 11.0


def test_ledger_rows_round_trip():
    a = PAPER.PaperLedger(":memory:")
    rows = [{c: None for c in PAPER.COLUMNS} | {"decision_id": "x", "mode": "LIVE", "opened_at": "t", "status": "OPEN"}]
    PAPER.import_rows(a, rows)
    assert PAPER.export_rows(a)[0]["decision_id"] == "x"


def test_outlook_track_reports_expectancy_and_drawdown():
    import numpy as np
    import pandas as pd
    from goldquant import outlook_log as OLOG
    idx = pd.date_range("2025-01-01", periods=60, freq="D", tz="UTC")
    daily = pd.DataFrame({"close": np.linspace(100, 160, 60)}, index=idx)
    recs = [{"bar": idx[i].isoformat(), "horizon": "WEEK", "tilt": 1, "validated": False} for i in (0, 10, 20)]
    t = OLOG.resolve(recs, daily)["horizons"]["WEEK"]
    assert t["resolved"] == 3 and t["hits"] == 3 and t["expectancy_pct"] > 0 and t["max_drawdown_pct"] == 0
