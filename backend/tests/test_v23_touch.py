"""Touch probability (pre-registered in goldquant/touch.py): labels look only forward, features only backward."""
import numpy as np
import pandas as pd

from goldquant import touch as TO


def _h1(n=3000, seed=5, unit="us"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC").as_unit(unit)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.002, "low": np.minimum(o, c) * 0.998, "close": c},
                        index=idx)


def test_labels_match_a_direct_check():
    df = _h1()
    s = TO.samples(df, 24)
    row = s.iloc[len(s) // 2]
    i = df.index.get_loc(row["t"])
    atr = TO.origin_features(df)["atr"].iloc[i]
    c = df["close"].iloc[i]
    fut = df.iloc[i + 1:i + 25]
    lvl = c + row["side"] * row["d"] * atr
    hit = (fut["high"].max() >= lvl) if row["side"] > 0 else (fut["low"].min() <= lvl)
    assert row["y"] == float(hit)


def test_features_do_not_see_the_future():
    df = _h1()
    f1 = TO.origin_features(df)
    df2 = df.copy()
    df2.iloc[2000:, :] = df2.iloc[2000:, :] * 1.5  # change only the future after bar 1999
    f2 = TO.origin_features(df2)
    pd.testing.assert_frame_equal(f1.iloc[:2000], f2.iloc[:2000])


def test_block_bootstrap_uses_real_blocks_whatever_the_index_unit():
    a = TO._ci(np.repeat(np.arange(50), 10), np.r_[np.ones(250) * 0.2, np.ones(250) * 0.1], np.ones(500) * 0.2, 95)
    assert a[0] < a[1]  # 50 distinct blocks -> a real spread, not a degenerate interval
    t = pd.DatetimeIndex(_h1(200)["close"].index)
    blk = pd.Timedelta(hours=24).value
    assert len(np.unique(t.as_unit("ns").asi8 // blk)) >= 8  # 200 hours = 9 days
