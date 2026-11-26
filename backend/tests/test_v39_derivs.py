from goldquant.sources import derivs as DV


def _payload(funding="0.00012", oi="1000", mark="70"):
    return [{"universe": [{"name": "BTC"}, {"name": "SOL"}, {"name": "ETH"}]},
            [{"funding": "0.00001", "openInterest": "10", "markPx": "90000"},
             {"funding": funding, "openInterest": oi, "markPx": mark},
             {"funding": "-0.0002", "openInterest": "5", "markPx": "3000"}]]


def test_parse_funding_and_oi():
    DV._oi_hist.update({a: [] for a in DV.ASSETS})
    out = DV.parse(_payload(), 1_000_000.0)
    assert out["SOL"]["funding_hourly"] == 0.00012
    assert out["SOL"]["open_interest_usd"] == 70000
    assert out["SOL"]["oi_change_24h_pct"] is None
    assert out["ETH"]["funding_hourly"] == -0.0002
    later = DV.parse(_payload(oi="1100"), 1_000_000.0 + 24 * 3600)
    assert later["SOL"]["oi_change_24h_pct"] == 10.0


def test_snapshot_survives_a_failing_source():
    DV._cache.update(at=0.0, data=None)
    def boom():
        raise RuntimeError("down")
    s = DV.snapshot(fetch=boom, now=5.0)
    assert s["state"] == "UNAVAILABLE" and s["assets"] == {}
