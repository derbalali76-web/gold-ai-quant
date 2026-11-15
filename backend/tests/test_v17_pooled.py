import numpy as np
import pandas as pd

from goldquant import pooled as P


def series(n=4200, seed=0, drift=0.0, start="2008-01-01", freq="B"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n))), index=idx)


def test_cot_is_used_only_after_release():
    rows = [{"report_date_as_yyyy_mm_dd": str(d.date()), "m_money_positions_long_all": "100",
             "m_money_positions_short_all": str(50 + i), "open_interest_all": "1000"}
            for i, d in enumerate(pd.date_range("2010-01-05", periods=200, freq="7D"))]
    c = P.parse_cot_rows(rows)
    idx = pd.date_range("2010-01-01", "2013-12-31", freq="D", tz="UTC")
    f = P.cot_features(idx, c)
    first_ok = f.index[f["has_cot"] == 1][0]
    assert first_ok >= c["usable"].iloc[0]
    # changing a report never changes features dated before it became usable
    rows2 = [dict(r) for r in rows]
    rows2[150]["m_money_positions_short_all"] = "900"
    f2 = P.cot_features(idx, P.parse_cot_rows(rows2))
    usable150 = P.parse_cot_rows(rows2)["usable"].iloc[150]
    assert f.loc[f.index < usable150].equals(f2.loc[f2.index < usable150])


def test_forward_return_is_nan_until_known():
    s = series(300)
    fr = P.forward_return(s, 7)
    assert fr.iloc[-1] != fr.iloc[-1]  # NaN
    assert np.isfinite(fr.iloc[:-10]).all()


def test_tournament_on_random_walks_does_not_qualify():
    closes = {a: series(seed=i, freq="D" if a in P.LONG_ONLY else "B") for i, a in
              enumerate(["XAU", "BTC", "ETH", "SOL", "EUR", "JPY", "WTI", "NASDAQ"])}
    out = P.tournament(closes, {})
    assert out["results"] and not any(r["qualified"] for r in out["results"])
    for r in out["results"]:
        if r.get("trades"):
            assert r["trades"] <= r["days"]
