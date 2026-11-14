"""Consensus-forecast recorder: point in time, append-only, change-only."""
from datetime import datetime, timezone

from goldquant.sources import ff_calendar as FF

PAYLOAD = [
    {"title": "CPI m/m", "country": "USD", "date": "2026-11-18T08:30:00-05:00", "impact": "High",
     "forecast": "0.3%", "previous": "0.4%"},
    {"title": "German ZEW", "country": "EUR", "date": "2026-11-18T05:00:00-05:00", "impact": "High", "forecast": "1"},
    {"title": "Bank Holiday", "country": "USD", "date": "2026-11-26T00:00:00-05:00", "impact": "Holiday"},
]


def test_records_only_usd_high_medium_and_only_changes(tmp_path):
    p = tmp_path / "ff.jsonl"
    t1 = datetime(2026, 11, 16, 8, tzinfo=timezone.utc)
    assert FF.record(FF.parse(PAYLOAD), p, t1) == 1
    assert FF.record(FF.parse(PAYLOAD), p, t1) == 0  # unchanged -> nothing new
    changed = [dict(PAYLOAD[0], forecast="0.2%")] + PAYLOAD[1:]
    assert FF.record(FF.parse(changed), p, t1) == 1
    with_actual = [dict(PAYLOAD[0], forecast="0.2%", actual="0.5%")]
    assert FF.record(FF.parse(with_actual), p, t1) == 1
    lines = p.read_text().splitlines()
    assert len(lines) == 3 and '"seen_at"' in lines[0] and '"actual": "0.5%"' in lines[2]
