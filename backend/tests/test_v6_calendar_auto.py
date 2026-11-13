"""Automatic official calendar (BLS iCal + Fed FOMC page), merge with the manual file, safe failure."""
import json
from datetime import datetime, timedelta, timezone

from goldquant.providers.http import HttpClient, Response
from goldquant.sources import calendar as CAL
from goldquant.sources import calendar_auto as CA

ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
DTSTART;TZID=US-Eastern:20261204T083000\r
SUMMARY:Employment Situation for November 2026\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;TZID=US-Eastern:20261210T083000\r
SUMMARY:Consumer Price Index for Novem\r
 ber 2026\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART:20261211T133000Z\r
SUMMARY:Producer Price Index for November 2026\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20261225\r
SUMMARY:Christmas Day\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;TZID=US-Eastern:20261120T100000\r
SUMMARY:Employment Situation of Veterans 2025\r
END:VEVENT\r
END:VCALENDAR\r
"""
FOMC = """<html><h4>2026 FOMC Meetings</h4><div class="fomc-meeting__month"><strong>October</strong></div>
<div class="fomc-meeting__date">27-28</div><div class="fomc-meeting__month"><strong>December</strong></div>
<div class="fomc-meeting__date">8-9*</div><h4>2027 FOMC Meetings</h4><div><strong>January</strong></div>
<div>26-27</div></html>"""
NOW = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)


def _http(routes):
    def t(url, params, timeout):
        body, code = routes.get(url, ("", 404))
        return Response(code, body, url, 1.0)
    return HttpClient(transport=t, retries=0)


def test_parse_bls_ics_times_and_filter():
    ev = CA.parse_bls_ics(ICS)
    names = [e["name"] for e in ev]
    assert names == ["US Nonfarm Payrolls (Employment Situation)", "US CPI", "US PPI"]  # veterans/holiday dropped
    assert ev[0]["time_utc"] == "2026-12-04T13:30:00Z"  # 08:30 EST = 13:30 UTC
    assert ev[0]["importance"] == 3 and ev[2]["importance"] == 2


def test_parse_fomc_decision_day_and_dst():
    ev = CA.parse_fomc_html(FOMC)
    assert [e["time_utc"] for e in ev] == ["2026-10-28T18:00:00Z", "2026-12-09T19:00:00Z", "2027-01-27T19:00:00Z"]


def test_build_merges_and_calendar_connects(tmp_path):
    http = _http({CA.BLS_ICS: (ICS, 200), CA.FOMC_URL: (FOMC, 200)})
    p = tmp_path / "calendar_auto.json"
    r = CA.refresh(p, NOW, http)
    assert r["written"] and r["sources"] == {"bls": "ok", "fomc": "ok"}
    manual = tmp_path / "calendar.json"
    manual.write_text(json.dumps({"updated_at": "2026-01-01T00:00:00Z", "events": [
        {"time_utc": "2026-11-26T13:30:00Z", "name": "US GDP", "importance": 3}]}), encoding="utf-8")
    cal = CAL.load_calendars([manual, p])
    assert cal.connected(NOW)  # manual file is stale but the automatic one is fresh
    assert "US GDP" in [e.name for e in cal.events]
    nfp = datetime(2026, 12, 4, 13, 30, tzinfo=timezone.utc)
    assert [e.name for e in cal.embargo(nfp - timedelta(minutes=55), 60, 45)] == ["US Nonfarm Payrolls (Employment Situation)"]


def test_total_failure_keeps_old_file_and_partial_failure_keeps_old_events(tmp_path):
    p = tmp_path / "calendar_auto.json"
    CA.refresh(p, NOW, _http({CA.BLS_ICS: (ICS, 200), CA.FOMC_URL: (FOMC, 200)}))
    before = p.read_text(encoding="utf-8")
    assert CA.refresh(p, NOW + timedelta(hours=7), _http({}))["written"] is False
    assert p.read_text(encoding="utf-8") == before  # nothing overwritten; it will age into "disconnected"
    r = CA.refresh(p, NOW + timedelta(hours=7), _http({CA.FOMC_URL: (FOMC, 200)}))  # BLS down only
    names = [e["name"] for e in json.loads(p.read_text(encoding="utf-8"))["events"]]
    assert r["written"] and "US CPI" in names and "kept previous" in r["sources"]["bls"]


def test_stale_auto_calendar_disconnects():
    old = CAL.Calendar([CAL.CalendarEvent(NOW + timedelta(days=3), "US CPI", 3, "bls.gov")], NOW - timedelta(days=9))
    assert not old.connected(NOW)
