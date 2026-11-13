"""Provider-contract tests with payloads in the documented formats (offline). Live checks: tools/live_contract_check.py."""
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from goldquant.providers.history import HistoryStore
from goldquant.providers.http import HttpClient, HttpError, RateLimiter, Response, redact
from goldquant.providers.live import LiveProvider
from goldquant.providers.twelvedata import ProviderError, TwelveDataProvider, parse_time_series
from goldquant.providers.xaus import XausSpot, parse_spot
from goldquant.sources import calendar as CAL
from goldquant.sources.cftc import footprint_as_of, parse_cot
from goldquant.sources.fred import SERIES, parse_fredgraph_csv
from goldquant.sources.news import cluster, parse_feed, recent_high_impact

NOW = datetime(2026, 1, 7, 14, 0, tzinfo=timezone.utc)


# ---------------- HTTP layer
def test_retry_then_success_and_no_retry_on_401():
    calls = []

    def t(url, params, timeout):
        calls.append(1)
        return Response(503 if len(calls) < 3 else 200, "ok", url, 5.0)
    c = HttpClient(transport=t, retries=3, sleep=lambda s: None)
    assert c.get("https://x").text == "ok" and len(calls) == 3
    calls.clear()
    c2 = HttpClient(transport=lambda u, p, t: (calls.append(1), Response(401, "", u + "?apikey=SECRET", 1))[1],
                    sleep=lambda s: None)
    with pytest.raises(HttpError) as e:
        c2.get("https://x")
    assert len(calls) == 1 and "SECRET" not in str(e.value)


def test_network_failure_raises_after_retries():
    def boom(*a):
        raise ConnectionError("down")
    with pytest.raises(HttpError):
        HttpClient(transport=boom, retries=2, sleep=lambda s: None).get("https://x")


def test_rate_limiter_waits():
    t = [0.0]
    waits = []
    rl = RateLimiter(calls=2, period=60, clock=lambda: t[0], sleep=lambda s: (waits.append(s), t.__setitem__(0, t[0] + s)))
    for _ in range(3):
        rl.acquire()
    assert waits and waits[0] == pytest.approx(60)


def test_redact():
    assert redact("https://a?apikey=abc&x=1") == "https://a?apikey=***&x=1"


# ---------------- Twelve Data
TS = {"meta": {"symbol": "XAU/USD", "interval": "15min", "exchange_timezone": "UTC"}, "status": "ok",
      "values": [{"datetime": "2026-01-07 13:30:00", "open": "2650.1", "high": "2652.0", "low": "2649.5", "close": "2651.2"},
                 {"datetime": "2026-01-07 13:15:00", "open": "2649.0", "high": "2650.5", "low": "2648.0", "close": "2650.1"}]}


def test_parse_time_series_sorted_utc():
    df = parse_time_series(json.dumps(TS))
    assert str(df.index.tz) == "UTC" and df.index.is_monotonic_increasing and df["close"].iloc[-1] == 2651.2


@pytest.mark.parametrize("payload", ['{"code":429,"message":"limit","status":"error"}', '{"values":[]}', "<html>"])
def test_parse_time_series_errors(payload):
    with pytest.raises(ProviderError):
        parse_time_series(payload)


def _td_transport(now_minute):
    def t(url, params, timeout):
        iv = params["interval"]
        step = {"1min": 1, "15min": 15, "1h": 60, "4h": 240}[iv]
        n = min(int(params["outputsize"]), 400)
        end = now_minute - pd.Timedelta(minutes=step)
        idx = pd.date_range(end=end, periods=n, freq=f"{step}min")
        vals = [{"datetime": str(i.tz_localize(None)), "open": "2000", "high": "2001", "low": "1999", "close": f"{2000 + k * 0.01:.2f}"}
                for k, i in enumerate(idx)]
        return Response(200, json.dumps({"status": "ok", "values": vals}), url, 10)
    return t


def test_twelvedata_quote_is_last_closed_minute_and_bars_go_to_history():
    now = pd.Timestamp("2026-01-07 14:00:30", tz="UTC")
    hs = HistoryStore()
    p = TwelveDataProvider("KEY", hs, HttpClient(transport=_td_transport(now.floor("min")), sleep=lambda s: None),
                           clock=lambda: now.to_pydatetime())
    q = p.quote(now.to_pydatetime())
    assert q.observed_at <= now.to_pydatetime() and (now.to_pydatetime() - q.observed_at).total_seconds() < 120
    b = p.bars("M15", now.to_pydatetime(), 100)
    assert len(b.df) == 100 and (b.df.index + pd.Timedelta(minutes=15) <= now).all()
    assert hs.count_bars("TwelveData", "XAU/USD", "M15") > 0
    m30 = p.bars("M30", now.to_pydatetime(), 50)
    assert m30 is not None and (m30.df.index.minute % 30 == 0).all()
    assert any(r["ok"] for r in hs.recent_fetches())


def test_twelvedata_without_key_is_unconfigured():
    p = TwelveDataProvider("", HistoryStore())
    assert p.quote(NOW) is None and p.bars("M15", NOW, 10) is None


# ---------------- xaus cross-check
def test_parse_spot_and_cross_check():
    q = parse_spot(json.dumps({"spot_usd_oz": 2651.3, "updated_at": "2026-01-07T13:59:50Z"}), NOW)
    assert q.price == 2651.3 and q.observed_at.tzinfo is not None

    class P:
        meta = TwelveDataProvider.meta

        def __init__(self, price):
            self.price = price

        def quote(self, as_of):
            from goldquant.providers.base import Quote
            return Quote(self.price, NOW - timedelta(seconds=30), NOW, "TwelveData")

        def bars(self, *a):
            return None

    class C:
        last_error = None

        def __init__(self, price):
            self.price = price

        def quote(self):
            from goldquant.providers.base import Quote
            return Quote(self.price, NOW - timedelta(seconds=20), NOW, "xaus.com")

    assert LiveProvider(P(2651.0), C(2651.5)).quote(NOW).warnings == []
    assert LiveProvider(P(2651.0), C(2700.0)).quote(NOW).warnings  # 1.8 % apart


# ---------------- FRED
def test_fred_parse_and_publication_lag():
    csv = "observation_date,DFII10\n2026-01-05,1.85\n2026-01-06,.\n2026-01-07,1.90\n"
    rows = parse_fredgraph_csv(csv, SERIES["DFII10"], NOW)
    assert len(rows) == 2
    assert all(datetime.fromisoformat(r["published_at"]) > datetime.fromisoformat(r["observed_at"]) for r in rows)
    old = parse_fredgraph_csv("DATE,CPIAUCSL\n2025-11-01,320.1\n", SERIES["CPIAUCSL"], NOW)
    assert old[0]["meta"]["revision_risk"] is True


def test_history_as_of_respects_publication():
    hs = HistoryStore()
    rows = parse_fredgraph_csv("observation_date,DGS10\n2026-01-05,4.1\n2026-01-06,4.2\n", SERIES["DGS10"], NOW)
    hs.upsert_observations("FRED", "DGS10", rows)
    seen = hs.load_observations_as_of("FRED", "DGS10", datetime(2026, 1, 7, 0, 0, tzinfo=timezone.utc))
    assert list(seen["value"]) == [4.1]  # the 6th is not yet published on the 7th 00:00


# ---------------- CFTC
def _cot_rows(n=60):
    base = pd.Timestamp("2025-01-07")
    return json.dumps([{"report_date_as_yyyy_mm_dd": (base + pd.Timedelta(weeks=i)).strftime("%Y-%m-%dT00:00:00.000"),
                        "m_money_positions_long_all": str(150000 + 1000 * i), "m_money_positions_short_all": "30000",
                        "open_interest_all": "500000"} for i in range(n)])


def test_cot_published_after_tuesday_and_footprint():
    cot = parse_cot(_cot_rows(), NOW)
    assert (cot["published_at"] - cot["observed_at"] >= pd.Timedelta(days=3)).all()
    fp = footprint_as_of(cot, cot["published_at"].iloc[-1].to_pydatetime())
    assert fp["percentile_3y"] == 1.0 and fp["crowded"] == "LONG"
    before = footprint_as_of(cot, (cot["published_at"].iloc[-1] - pd.Timedelta(hours=1)).to_pydatetime())
    assert before["report_date"] != fp["report_date"]  # last report not visible before its release


# ---------------- News
RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Federal Reserve issues FOMC statement</title><link>https://fed/1</link><pubDate>Wed, 07 Jan 2026 13:45:00 GMT</pubDate></item>
<item><title>Board announces approval of bank merger</title><link>https://fed/2</link><pubDate>Wed, 07 Jan 2026 10:00:00 GMT</pubDate></item>
<item><title>No date item</title><link>x</link></item>
</channel></rss>"""
RSS2 = """<?xml version="1.0"?><rss><channel>
<item><title>FOMC statement issued by Federal Reserve</title><link>https://w/1</link><pubDate>Wed, 07 Jan 2026 13:47:30 GMT</pubDate></item>
</channel></rss>"""


def test_news_parse_classify_cluster_propagation_embargo():
    a = parse_feed(RSS, "federalreserve.gov", 1.0, NOW)
    b = parse_feed(RSS2, "wire", 0.8, NOW)
    assert len(a) == 2  # undated item dropped
    assert a[0].event_type == "MONETARY_POLICY" and a[0].importance == 3
    cl = cluster(a + b)
    fomc = [c for c in cl if len(c.items) == 2][0]
    assert fomc.first.source == "federalreserve.gov" and fomc.propagation()[1]["delay_s"] == 150
    assert recent_high_impact(cl, NOW)  # 15 min after a high-impact item -> embargo
    assert not recent_high_impact(cl, NOW + timedelta(hours=2))


def test_news_rejects_xml_bombs():
    bomb = '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><rss>&b;</rss>'
    with pytest.raises(Exception):
        parse_feed(bomb, "x", 1, NOW)


# ---------------- Calendar
def test_calendar_connected_and_embargo(tmp_path):
    p = tmp_path / "calendar.json"
    p.write_text(json.dumps({"updated_at": "2026-01-05T00:00:00Z", "events": [
        {"time_utc": "2026-01-07T13:30:00Z", "name": "US CPI", "importance": 3, "source": "bls.gov", "consensus": 0.3},
        {"time_utc": "2026-01-09T13:30:00Z", "name": "NFP", "importance": 3, "source": "bls.gov"}]}))
    cal = CAL.load_calendar(p)
    assert cal.connected(NOW)
    assert [e.name for e in cal.embargo(NOW)] == ["US CPI"]  # 30 min after release
    assert not cal.connected(NOW + timedelta(days=30))
    assert not CAL.load_calendar(tmp_path / "missing.json").connected(NOW)
