"""Is the scalping target itself achievable? Base rates before any model (BTC, ETH, SOL, 1-minute data).

Question: from a random entry, how often does the price reach +TARGET before the stop, within W minutes, and what
does that leave after costs? Split by coin, hour of day (UTC), market activity (out-of-sample forecast) and year.
Compared with a DYNAMIC target scaled to recent volatility. Descriptive study: nothing here is a trading rule.

Method (fixed in advance):
  entries   every 5th 1-minute close (the next bars decide; no information from the future is used to choose)
  windows   15, 30, 60 minutes
  fixed     target +0.65 %, stops 0.40 % and 0.65 % (long side; the short side is reported for perpetual users)
  dynamic   target = stop = k x sigma, sigma = stdev of 1-min log returns over the previous 60 min x sqrt(W),
            k in {1.0, 1.5, 2.0}
  touches   stop counted first when one bar touches both; a limit target needs a trade 0.01 % through it
  costs     0.15 % fees + 0.01-0.02 % spread; +0.02 % slippage on stop / timeout exits
  outputs   P(target first), P(stop first), P(neither), average net per entry, break-even P for the target/stop pair
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TARGET = 0.0065
STOPS = (0.0040, 0.0065)
WINDOWS = (15, 30, 60)
KS = (1.0, 1.5, 2.0)
STEP = 5
FEES, SLIP, THROUGH = 0.0015, 0.0002, 0.0001
SPREAD = {"BTC": 0.0001, "ETH": 0.0001, "SOL": 0.0002}


def first_passage(h, lo, c, entries, window, tgt, stp, side=1):
    """Vectorised outcome per entry: 1 target first, -1 stop first, 0 neither; plus the exit return (gross)."""
    n = len(c)
    e = c[entries]
    out = np.zeros(len(entries), np.int8)
    ret = np.zeros(len(entries))
    done = np.zeros(len(entries), bool)
    tgt = np.broadcast_to(tgt, e.shape)
    stp = np.broadcast_to(stp, e.shape)
    for j in range(1, window + 1):
        k = np.minimum(entries + j, n - 1)
        if side == 1:
            hit_s = lo[k] <= e * (1 - stp)
            hit_t = h[k] >= e * (1 + tgt) * (1 + THROUGH)
        else:
            hit_s = h[k] >= e * (1 + stp)
            hit_t = lo[k] <= e * (1 - tgt) * (1 - THROUGH)
        s_new = hit_s & ~done
        out[s_new], ret[s_new] = -1, -stp[s_new]
        done |= s_new
        t_new = hit_t & ~done
        out[t_new], ret[t_new] = 1, tgt[t_new]
        done |= t_new
    k = np.minimum(entries + window, n - 1)
    ret[~done] = side * (c[k[~done]] / e[~done] - 1)
    return out, ret


def _net(out, ret, asset):
    cost = FEES + SPREAD.get(asset, 0.0002)
    return ret - cost - np.where(out == 1, 0.0, SLIP)


def _summ(out, net, tgt, stp, asset):
    cost = FEES + SPREAD.get(asset, 0.0002)
    pt, ps = float((out == 1).mean()), float((out == -1).mean())
    t = float(np.mean(tgt)) if np.ndim(tgt) else tgt
    s = float(np.mean(stp)) if np.ndim(stp) else stp
    return {"n": int(len(out)), "p_target": round(pt, 4), "p_stop": round(ps, 4), "p_neither": round(1 - pt - ps, 4),
            "avg_net_pct": round(float(net.mean()) * 100, 4),
            "breakeven_p_target": round((s + cost + SLIP) / (t + s + SLIP), 4),
            "avg_target_pct": round(t * 100, 3)}


def study(m1: pd.DataFrame, asset: str, activity_high: np.ndarray | None = None) -> dict:
    m1 = m1.dropna(subset=["open", "high", "low", "close"])
    h, lo, c = (m1[k].to_numpy(float) for k in ("high", "low", "close"))
    lr = np.diff(np.log(c), prepend=np.log(c[0]))
    sig60 = pd.Series(lr).rolling(60, min_periods=50).std().to_numpy()
    entries = np.arange(60, len(c) - max(WINDOWS) - 1, STEP)
    entries = entries[np.isfinite(sig60[entries])]
    t_close = m1.index[entries] + pd.Timedelta(minutes=1)
    hours, years = t_close.hour.to_numpy(), t_close.year.to_numpy()
    res = {"asset": asset, "period": f"{m1.index[0].date()} -> {m1.index[-1].date()}", "entries": int(len(entries)),
           "fixed": [], "dynamic": [], "by_hour": {}, "by_activity": {}, "by_year": {}}
    for w in WINDOWS:
        for s in STOPS:
            for side in (1, -1):
                out, ret = first_passage(h, lo, c, entries, w, TARGET, s, side)
                net = _net(out, ret, asset)
                row = {"window_min": w, "stop_pct": s * 100, "side": "LONG" if side == 1 else "SHORT",
                       **_summ(out, net, TARGET, s, asset)}
                res["fixed"].append(row)
                if w == 30 and side == 1 and s == 0.0040:  # the reference case for the splits
                    for hr in range(24):
                        m = hours == hr
                        res["by_hour"][str(hr)] = _summ(out[m], net[m], TARGET, s, asset)
                    for y in sorted(set(years)):
                        m = years == y
                        res["by_year"][str(y)] = _summ(out[m], net[m], TARGET, s, asset)
                    if activity_high is not None:
                        a = activity_high[entries]
                        for name, m in (("HIGH", a == 1), ("NOT_HIGH", a == 0)):
                            if m.sum() > 100:
                                res["by_activity"][name] = _summ(out[m], net[m], TARGET, s, asset)
        for k in KS:
            tg = k * sig60[entries] * np.sqrt(w)
            out, ret = first_passage(h, lo, c, entries, w, tg, tg, 1)
            net = _net(out, ret, asset)
            res["dynamic"].append({"window_min": w, "k": k, "side": "LONG", **_summ(out, net, tg, tg, asset)})
    return res
