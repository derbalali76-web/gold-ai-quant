from goldquant import push as P


def test_recent_extremes_from_minute_bars():
    rows = [[0, "70", "70.6", "69.9", "70.2"], [0, "70.2", "70.9", "70.1", "70.3"]]
    hi, lo = P.recent_extremes("SOL", 1000.0, 1300.0, fetch=lambda s, t: rows)
    assert hi == 70.9 and lo == 69.9
    assert P.recent_extremes("XAU", 1000.0, 1300.0, fetch=lambda s, t: rows) == (None, None)
    def boom(s, t):
        raise RuntimeError("x")
    assert P.recent_extremes("BTC", 1000.0, 1300.0, fetch=boom) == (None, None)
