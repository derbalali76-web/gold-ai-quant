"""Audit 2026-11-15: fixes that change no engine methodology and no approval rule."""
import json
import time

import numpy as np
import pandas as pd

from goldquant import activity as A
from goldquant import crypto_engine as CE
from goldquant import pooled as PO


# ---------------- crypto feed: a bar still forming when the data was downloaded is never served as closed
def _kl(open_ms, n, step_ms):
    return [[open_ms + i * step_ms, "1", "2", "0.5", "1.5", "10", open_ms + (i + 1) * step_ms - 1, "0", 1, "5", "0", "0"]
            for i in range(n)]


def test_cached_forming_bar_is_not_served_as_closed(monkeypatch):
    t0 = pd.Timestamp("2026-11-15 10:00", tz="UTC")
    calls = []

    class Http:
        def get(self, url, params):
            calls.append(params)
            # downloaded at 10:14:30: the 10:00 bar is still forming
            return type("R", (), {"text": json.dumps(_kl(int((t0 - pd.Timedelta(minutes=150)).value // 10**6), 11,
                                                         15 * 60 * 1000))})()
    feed = CE.CryptoFeed(http=Http())
    now = [(t0 + pd.Timedelta(minutes=14, seconds=30)).timestamp()]
    monkeypatch.setattr(CE.time, "time", lambda: now[0])
    a = feed.bars("BTCUSDT", "M15", (t0 + pd.Timedelta(minutes=14, seconds=30)).to_pydatetime())
    assert a.index[-1] == t0 - pd.Timedelta(minutes=15)  # 10:00 bar not closed yet
    now[0] = (t0 + pd.Timedelta(minutes=15, seconds=30)).timestamp()  # 60 s later, cache still "fresh"
    b = feed.bars("BTCUSDT", "M15", (t0 + pd.Timedelta(minutes=15, seconds=30)).to_pydatetime())
    assert len(calls) == 2  # a bar closed since the download -> fetched again, not reused
    assert b.index[-1] <= t0  # and never a bar whose close is after the download time
    now[0] = (t0 + pd.Timedelta(minutes=16)).timestamp()
    feed.bars("BTCUSDT", "M15", (t0 + pd.Timedelta(minutes=16)).to_pydatetime())
    assert len(calls) == 2  # nothing closed since the second download: cache reused


# ---------------- activity: no probability shown where calibration was never tested
def test_calibrated_bins_and_hidden_probability():
    rep = {"calibration": [{"bin": "0-20%", "n": 53, "predicted": 0.10, "actual": 0.57},
                           {"bin": "35-50%", "n": 532, "predicted": 0.40, "actual": 0.44},
                           {"bin": "80-100%", "n": 40071, "predicted": 0.96, "actual": 0.957}]}
    assert A.calibrated_bins(rep) == [[0.35, 0.5], [0.8, 1.01]]
    assert A.calibrated_bins({}) is None
    from tests.test_v15_activity import frame
    d = frame()
    params = A.export(d, {"qualified": True})
    p = A.predict(params, d.iloc[-1000:])["probability"]
    assert A.predict(dict(params, calibrated_bins=[[0.0, 1.01]]), d.iloc[-1000:]) is not None
    lo = [[0.0, max(0.0, p - 0.01)]]  # a calibrated range that excludes today's probability
    assert A.predict(dict(params, calibrated_bins=lo), d.iloc[-1000:]) is None


# ---------------- COT: shutdown-delayed reports usable only after their real publication
def test_cot_delayed_reports_follow_real_publication():
    rows = [{"report_date_as_yyyy_mm_dd": d, "m_money_positions_long_all": "10", "m_money_positions_short_all": "5",
             "open_interest_all": "100"} for d in ("2025-09-23", "2025-09-30", "2025-10-07", "2019-01-15", "2024-05-07")]
    c = PO.parse_cot_rows(rows).set_index(PO.parse_cot_rows(rows)["report"].dt.strftime("%Y-%m-%d"))["usable"]
    assert c["2025-09-23"] == pd.Timestamp("2025-09-29", tz="UTC")  # on time: report + 6 days (Monday)
    assert c["2025-09-30"] == pd.Timestamp("2025-11-24", tz="UTC")  # published 19 Nov 2025 -> Monday 24 Nov
    assert c["2025-10-07"] == pd.Timestamp("2025-11-24", tz="UTC")  # published Fri 21 Nov -> Monday 24 Nov
    assert c["2019-01-15"] == pd.Timestamp("2019-03-11", tz="UTC")  # 2018-19 backlog: after the catch-up
    assert c["2024-05-07"] == pd.Timestamp("2024-05-13", tz="UTC")


def test_cot_features_never_use_a_report_before_it_is_usable():
    rng = np.random.default_rng(1)
    reports = pd.date_range("2022-01-04", "2026-01-27", freq="7D", tz="UTC")
    rows = [{"report_date_as_yyyy_mm_dd": str(d.date()), "m_money_positions_long_all": str(50 + rng.integers(0, 40)),
             "m_money_positions_short_all": "30", "open_interest_all": "200"} for d in reports]
    cot = PO.parse_cot_rows(rows)
    idx = pd.date_range("2025-09-01", "2026-01-15", freq="D", tz="UTC")
    f = PO.cot_features(idx, cot)
    for t in idx:
        usable = cot[cot["usable"] <= t]
        if len(usable) and f.loc[t, "has_cot"] == 1.0:
            assert f.loc[t, "cot_net"] == usable.sort_values(["usable", "report"]).iloc[-1]["net"]
    # during the blackout nothing newer than the last on-time report (23 Sep 2025) is used
    last_on_time = cot.set_index("report").loc[pd.Timestamp("2025-09-23", tz="UTC"), "net"]
    assert f.loc[pd.Timestamp("2025-11-10", tz="UTC"), "cot_net"] == last_on_time


# ---------------- ledger rule 2: a snapshot older than 20 minutes records nothing (price no longer tradable)
def test_ledger_needs_a_snapshot_at_most_20_minutes_old(tmp_path):
    from datetime import timedelta
    from tests.test_v10_ledger import BUY, L, T0, snap
    led = L.Ledger(tmp_path)
    led.ingest(snap(T0, [BUY]), T0 + timedelta(minutes=25))
    assert not [e for e in led.entries if e["kind"] == "REC"]
    led.ingest(snap(T0, [BUY]), T0 + timedelta(minutes=15))
    assert [e for e in led.entries if e["kind"] == "REC"]
