"""Scalping engine, experiment 2: predict P(+target is reached BEFORE the stop within W minutes) — not the next candle.

PRE-REGISTERED 2026-11-15, BEFORE any result was seen (research only; nothing reaches production unless it passes).

Data       Binance spot 1-minute klines (real volume, taker-buy volume) + perpetual funding (8-hourly, known at its
           timestamp) for BTC, ETH, SOL; decisions every 5 minutes at a 5-minute close. Order-book history is not
           used (not available for spot; to be checked separately).
Label      long side; target +0.65 %; stops 0.40 % and 0.65 %; windows 30 and 60 min; same-bar touch = stop; the target
           needs a trade 0.01 % through it. 4 label configurations.
Features   (closed bars only) returns over 1/5/15/30/60/240 min scaled by volatility; realised volatility 15/60/240;
           position in the 60 and 240-min range; taker-buy share 5/15/60; volume vs 1 day; distance to EMA20/50 of
           5-min and 15-min closes; 1-hour trend; hour of day; weekend; last known funding rate.
Models     LOGIT (logistic, C=0.1) and LGBM (LightGBM: 300 trees, 31 leaves, lr 0.03, min 500 per leaf, subsample
           0.8, feature fraction 0.8; scikit-learn's histogram GBDT if LightGBM is not installed — recorded).
Training   expanding window, re-fitted at the start of every calendar year from 2022, on rows whose outcome was known
           before the year started (purge = window + 1 day). Fixed settings: nothing is tuned on test data.
Rule       enter at the NEXT 1-minute open (market, +0.02 % slippage) when P >= break-even P + 0.05, one trade at a
           time (no stacking -> the number of trades cannot be inflated). Costs: 0.15 % fees + spread (0.01 % BTC/ETH,
           0.02 % SOL) + 0.02 % slippage on entry and on stop/timeout exits.
Baselines  (a) the same number of entries at evenly spaced times; (b) entries only when the market-activity
           forecast is HIGH (simple rule, same exits).
Judging    24 combinations (4 labels x 2 models x 3 coins) -> 99.8 % confidence. Qualifies only if ALL hold:
           >= 200 trades; average net CI above zero; every year positive (>= 20 trades); final holdout (last 20 % of
           time, never used to choose anything) positive with >= 50 trades; beats both baselines (CI above zero);
           probabilities calibrated on the holdout (Brier better than the training base rate).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

VERSION = "scalp-ml-1"
TARGET = 0.0065
STOPS = (0.0040, 0.0065)
WINDOWS = (30, 60)
MODELS = ("LOGIT", "LGBM")
MARGIN = 0.05
FEES, SLIP, THROUGH = 0.0015, 0.0002, 0.0001
SPREAD = {"BTC": 0.0001, "ETH": 0.0001, "SOL": 0.0002}
CI_LEVEL = 99.8
HOLDOUT_FRAC = 0.2
FIRST_TEST_YEAR = 2022
FEATURES = ["r1", "r5", "r15", "r30", "r60", "r240", "rv15", "rv60", "rv240", "rp60", "rp240", "tb5", "tb15", "tb60",
            "volz", "e5_20", "e5_50", "e15_20", "e15_50", "trend1h", "hsin", "hcos", "wkend", "funding"]


def features(m1: pd.DataFrame, funding: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Per 1-minute bar, using only that bar and earlier ones (index = bar open; known at open + 1 min)."""
    c = m1["close"].astype(float)
    lr = np.log(c).diff()
    s1 = lr.rolling(240, min_periods=120).std()
    f = pd.DataFrame(index=m1.index)
    for n in (1, 5, 15, 30, 60, 240):
        f[f"r{n}"] = np.log(c / c.shift(n)) / (s1 * np.sqrt(n))
    for n in (15, 60, 240):
        f[f"rv{n}"] = np.log(lr.rolling(n, min_periods=n // 2).std() + 1e-7)
    for n in (60, 240):
        lo, hi = m1["low"].rolling(n).min(), m1["high"].rolling(n).max()
        f[f"rp{n}"] = (c - lo) / (hi - lo).replace(0, np.nan) - 0.5
    v = m1["volume"].astype(float)
    tb = m1["taker_buy_volume"].astype(float) if "taker_buy_volume" in m1.columns else v * 0.5
    for n in (5, 15, 60):
        f[f"tb{n}"] = tb.rolling(n).sum() / v.rolling(n).sum().replace(0, np.nan) - 0.5
    f["volz"] = np.log((v.rolling(15).mean() + 1e-9) / (v.rolling(1440, min_periods=500).mean() + 1e-9))
    for span_min, tag in ((5, "e5"), (15, "e15")):
        cc = c.resample(f"{span_min}min").last().dropna()
        for n in (20, 50):
            e = cc.ewm(span=n, adjust=False).mean()
            # value of the last CLOSED higher-TF bar at each minute
            avail = e.copy()
            avail.index = avail.index + pd.Timedelta(minutes=span_min)
            f[f"{tag}_{n}"] = (np.log(c) - np.log(avail.reindex(f.index + pd.Timedelta(minutes=1), method="ffill")
                                                    .to_numpy())) / s1
    h1 = c.resample("60min").last().dropna()
    t = (h1 > h1.ewm(span=50, adjust=False).mean()).astype(float)
    t.index = t.index + pd.Timedelta(minutes=60)
    f["trend1h"] = t.reindex(f.index + pd.Timedelta(minutes=1), method="ffill").to_numpy() - 0.5
    ct = f.index + pd.Timedelta(minutes=1)
    hr = ct.hour + ct.minute / 60
    f["hsin"], f["hcos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    f["wkend"] = (ct.dayofweek >= 5).astype(float)
    f["funding"] = 0.0
    if funding is not None and len(funding):
        fr = funding["funding"].astype(float).sort_index()
        f["funding"] = fr.reindex(ct, method="ffill").fillna(0.0).to_numpy() * 1000
    return f.replace([np.inf, -np.inf], np.nan).astype(np.float32)


def outcomes(m1: pd.DataFrame, dec: np.ndarray, window: int, stop: float, asset: str):
    """Entry at the next minute's open (+slippage); returns (label, net return, exit index)."""
    o, h, lo, c = (m1[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    ei = np.minimum(dec + 1, n - 1)
    e = o[ei] * (1 + SLIP)
    lab = np.zeros(len(dec), np.int8)
    ret = np.zeros(len(dec))
    xi = np.minimum(ei + window - 1, n - 1)
    done = np.zeros(len(dec), bool)
    for j in range(0, window):
        k = np.minimum(ei + j, n - 1)
        hs = (lo[k] <= e * (1 - stop)) & ~done
        lab[hs], ret[hs], xi[hs] = -1, -stop - SLIP, k[hs]
        done |= hs
        ht = (h[k] >= e * (1 + TARGET) * (1 + THROUGH)) & ~done
        if j == 0:
            ht &= False  # a target inside the entry bar is not counted (order of events unknown)
        lab[ht], ret[ht], xi[ht] = 1, TARGET, k[ht]
        done |= ht
    rest = ~done
    ret[rest] = c[xi[rest]] * (1 - SLIP) / e[rest] - 1
    net = ret - FEES - SPREAD.get(asset, 0.0002)
    return lab, net, xi


def breakeven_p(stop: float, asset: str) -> float:
    cost = FEES + SPREAD.get(asset, 0.0002) + SLIP
    return (stop + SLIP + cost) / (TARGET + stop + SLIP)


def _model(kind: str):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if kind == "LGBM":
        try:
            import lightgbm as lgb
            return lgb.LGBMClassifier(n_estimators=300, num_leaves=31, learning_rate=0.03, min_child_samples=500,
                                      subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1,
                                      random_state=7), "lightgbm"
        except ImportError:
            from sklearn.ensemble import HistGradientBoostingClassifier
            return HistGradientBoostingClassifier(max_iter=300, max_leaf_nodes=31, learning_rate=0.03,
                                                  min_samples_leaf=500, random_state=7), "sklearn-hgb"
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=1000)), "logit"


def _boot(x, level=CI_LEVEL, n=2000, seed=7):
    if len(x) < 10:
        return None
    rng = np.random.default_rng(seed)
    m = np.array([np.mean(rng.choice(x, len(x))) for _ in range(n)])
    a = (100 - level) / 2
    return m, [round(float(np.percentile(m, a)) * 100, 4), round(float(np.percentile(m, 100 - a)) * 100, 4)]


def _take(dec_times, p, thr, xi_by_dec):
    """One trade at a time: walk the decisions in order, skip while a trade is open."""
    taken, free = [], -1
    for i in np.flatnonzero(p >= thr):
        if dec_times[i] <= free:
            continue
        taken.append(i)
        free = xi_by_dec[i]
    return np.array(taken, int)


def run_asset(m1: pd.DataFrame, asset: str, funding: Optional[pd.DataFrame] = None,
              activity_high: Optional[np.ndarray] = None) -> list[dict]:
    m1 = m1.dropna(subset=["open", "high", "low", "close"])
    F = features(m1, funding)
    idx = m1.index
    # decisions at 5-minute closes: the 1-min bar whose close ends a 5-minute block
    dec = np.flatnonzero(((idx + pd.Timedelta(minutes=1)).minute % 5) == 0)
    dec = dec[(dec > 1500) & (dec < len(m1) - max(WINDOWS) - 2)]
    X = F[FEATURES].to_numpy()[dec]
    ok = np.isfinite(X).all(axis=1)
    dec, X = dec[ok], X[ok]
    t_dec = idx[dec] + pd.Timedelta(minutes=1)
    years = t_dec.year.to_numpy()
    cut = idx[int(len(idx) * (1 - HOLDOUT_FRAC))]
    out = []
    for w in WINDOWS:
        for stop in STOPS:
            lab, net, xi = outcomes(m1, dec, w, stop, asset)
            y = (lab == 1).astype(int)
            known = idx[np.minimum(xi, len(idx) - 1)] + pd.Timedelta(days=1)  # purge: outcome known + 1 day
            thr = breakeven_p(stop, asset) + MARGIN
            for kind in MODELS:
                p = np.full(len(dec), np.nan)
                base = np.full(len(dec), np.nan)
                impl = None
                for yr in sorted(set(years)):
                    if yr < FIRST_TEST_YEAR:
                        continue
                    start = pd.Timestamp(f"{yr}-01-01", tz="UTC")
                    tr = np.flatnonzero(known < start)
                    te = np.flatnonzero(years == yr)
                    if len(tr) < 20000 or not len(te):
                        continue
                    tr = tr[::3]  # every 15 min for training (speed); prediction on every 5-min decision
                    m, impl = _model(kind)
                    m.fit(X[tr], y[tr])
                    p[te] = m.predict_proba(X[te])[:, 1]
                    base[te] = y[tr].mean()
                rep = _judge(asset, kind, impl, w, stop, thr, dec, t_dec, years, p, base, y, net, xi, cut,
                             activity_high, len(m1))
                out.append(rep)
    return out


def _judge(asset, kind, impl, w, stop, thr, dec, t_dec, years, p, base, y, net, xi, cut, activity_high, n_bars):
    rep = {"asset": asset, "model": kind, "implementation": impl, "window_min": w, "stop_pct": stop * 100,
           "target_pct": TARGET * 100, "threshold_p": round(thr, 4), "version": VERSION, "qualified": False}
    have = np.isfinite(p)
    if have.sum() < 5000:
        rep["reason"] = "insufficient data"
        return rep
    rep["decisions"] = int(have.sum())
    rep["max_p"] = round(float(np.nanmax(p)), 4)
    rep["share_above_threshold"] = round(float((p[have] >= thr).mean()), 5)
    # calibration on the holdout decisions
    ho = have & (t_dec >= cut)
    if ho.sum():
        rep["brier_holdout"] = round(float(np.mean((p[ho] - y[ho]) ** 2)), 5)
        rep["brier_base_holdout"] = round(float(np.mean((base[ho] - y[ho]) ** 2)), 5)
        rep["base_rate_holdout"] = round(float(y[ho].mean()), 4)
    pp = np.where(have, p, -1.0)
    taken = _take(dec, pp, thr, xi)
    rep["trades"] = int(len(taken))
    if len(taken) < 20:
        rep["reason"] = "too few trades (model rarely sees an edge above break-even)"
        rep["checks"] = {}
        return rep
    r = net[taken]
    rep["win_rate"] = round(float((r > 0).mean()), 4)
    rep["p_target_first"] = round(float((y[taken] == 1).mean()), 4)
    rep["avg_predicted_p"] = round(float(p[taken].mean()), 4)
    rep["avg_net_pct"] = round(float(r.mean()) * 100, 4)
    bm, rep["avg_net_ci"] = _boot(r)
    eq = np.cumsum(r)
    rep["total_net_pct"] = round(float(eq[-1]) * 100, 2)
    rep["max_drawdown_pct"] = round(float(np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq])) * 100, 2)
    weeks = max((t_dec[have][-1] - t_dec[have][0]).days / 7, 1)
    rep["trades_per_week"] = round(len(r) / weeks, 2)
    rep["years"] = {str(yy): {"trades": int((years[taken] == yy).sum()),
                              "avg_net_pct": round(float(r[years[taken] == yy].mean()) * 100, 4)}
                    for yy in sorted(set(years[taken]))}
    hmask = t_dec[taken] >= cut
    rep["holdout_trades"] = int(hmask.sum())
    rep["holdout_avg_pct"] = round(float(r[hmask].mean()) * 100, 4) if hmask.any() else None
    # baselines (same exits, same one-at-a-time rule)
    pool = np.flatnonzero(have)
    even = pool[np.linspace(0, len(pool) - 1, min(len(pool), len(taken) * 3)).astype(int)]
    b_even = _take(dec, np.where(np.isin(np.arange(len(dec)), even), 1.0, -1.0), 0.5, xi)
    rb = net[b_even]
    rep["baseline_even_avg_pct"] = round(float(rb.mean()) * 100, 4)
    bb, _ = _boot(rb, seed=8)
    a = (100 - CI_LEVEL) / 2
    rep["edge_vs_even_ci"] = [round(float(np.percentile(bm - bb, a)) * 100, 4),
                              round(float(np.percentile(bm - bb, 100 - a)) * 100, 4)]
    rep["edge_vs_activity_ci"] = None
    if activity_high is not None:
        act = activity_high[dec] == 1
        b_act = _take(dec, np.where(have & act, 1.0, -1.0), 0.5, xi)
        if len(b_act) >= 20:
            ra = net[b_act]
            rep["baseline_activity_avg_pct"] = round(float(ra.mean()) * 100, 4)
            ba, _ = _boot(ra, seed=9)
            rep["edge_vs_activity_ci"] = [round(float(np.percentile(bm - ba, a)) * 100, 4),
                                          round(float(np.percentile(bm - ba, 100 - a)) * 100, 4)]
    yrs = [v for v in rep["years"].values() if v["trades"] >= 20]
    ck = {
        "at least 200 trades": rep["trades"] >= 200,
        "average net CI above zero": rep["avg_net_ci"][0] > 0,
        "every year positive": bool(yrs) and all(v["avg_net_pct"] > 0 for v in yrs),
        "final holdout positive": rep["holdout_trades"] >= 50 and (rep["holdout_avg_pct"] or 0) > 0,
        "beats evenly-timed entries (CI)": rep["edge_vs_even_ci"][0] > 0,
        "beats activity-only rule (CI)": rep["edge_vs_activity_ci"] is None or rep["edge_vs_activity_ci"][0] > 0,
        "calibrated on holdout": rep.get("brier_holdout", 1) < rep.get("brier_base_holdout", 0),
    }
    rep["checks"] = ck
    rep["qualified"] = all(ck.values())
    rep["reason"] = "qualified" if rep["qualified"] else "failed: " + "; ".join(k for k, v in ck.items() if not v)
    return rep


# ---------------------------------------------------------------- EXPERIMENT 3: order book (pre-registered 2026-11-15)
BOOK_DOC = """Experiment 3 — does order-book depth add information? (pre-registered before any result)
  data      Binance USD-M futures bookDepth snapshots (cumulative notional within +-1/2/5 % of the price), from the
            first available day; a snapshot is used only from its own timestamp, and only if it is <= 5 minutes old
  features  imbalance (bid - ask)/(bid + ask) at 1, 2 and 5 %; its change over 5 and 15 minutes; total depth within
            5 % vs its 1-day average
  labels    (30 min, stop 0.40 %) and (60 min, stop 0.65 %), target +0.65 %, same execution and costs as experiment 2
  models    LOGIT and LGBM, each WITHOUT and WITH the book features (same rows, same folds) -> 4 candidates
  folds     re-fitted at the start of every calendar quarter once 2 quarters of data exist; last 20 % of time = holdout
  judging   same checks as experiment 2; 4 candidates x 2 labels x 3 coins = 24 tests -> 99.8 % confidence
  value     'book adds information' only if the paired out-of-sample Brier improvement has a 95 % day-block CI > 0"""
BOOK_FEATURES = ["imb1", "imb2", "imb5", "dimb1_5", "dimb1_15", "depth_z"]
BOOK_LABELS = ((30, 0.0040), (60, 0.0065))


def book_features(index: pd.DatetimeIndex, book: pd.DataFrame) -> pd.DataFrame:
    b = book.sort_index()
    b = b[~b.index.duplicated(keep="last")]
    b.index = b.index.as_unit(index.unit)
    f = pd.DataFrame(index=b.index)
    for lvl in (1, 2, 5):
        s = b[f"bid{lvl}"] + b[f"ask{lvl}"]
        f[f"imb{lvl}"] = (b[f"bid{lvl}"] - b[f"ask{lvl}"]) / s.replace(0, np.nan)
    f["depth"] = np.log(b["bid5"] + b["ask5"] + 1.0)
    f["snap_t"] = b.index
    close_t = index + pd.Timedelta(minutes=1)
    m = f.reindex(close_t, method="ffill")
    fresh = (close_t - pd.DatetimeIndex(m["snap_t"])) <= pd.Timedelta(minutes=5)
    out = pd.DataFrame(index=index)
    for k in ("imb1", "imb2", "imb5"):
        out[k] = np.where(fresh, m[k].to_numpy(), np.nan)
    i1 = pd.Series(out["imb1"].to_numpy(), index=index)
    out["dimb1_5"] = (i1 - i1.shift(5)).to_numpy()
    out["dimb1_15"] = (i1 - i1.shift(15)).to_numpy()
    dep = pd.Series(np.where(fresh, m["depth"].to_numpy(), np.nan), index=index)
    out["depth_z"] = (dep - dep.rolling(1440, min_periods=500).mean()).to_numpy()
    return out.astype(np.float32)


def run_book(m1: pd.DataFrame, asset: str, book: pd.DataFrame, funding: Optional[pd.DataFrame] = None,
             activity_high: Optional[np.ndarray] = None) -> dict:
    m1 = m1.dropna(subset=["open", "high", "low", "close"])
    m1 = m1[m1.index >= book.index.min() - pd.Timedelta(days=2)]
    F = features(m1, funding).join(book_features(m1.index, book))
    idx = m1.index
    dec = np.flatnonzero(((idx + pd.Timedelta(minutes=1)).minute % 5) == 0)
    dec = dec[(dec > 1500) & (dec < len(m1) - max(w for w, _ in BOOK_LABELS) - 2)]
    cols_all = FEATURES + BOOK_FEATURES
    X = F[cols_all].to_numpy()[dec]
    ok = np.isfinite(X).all(axis=1)
    dec, X = dec[ok], X[ok]
    t_dec = idx[dec] + pd.Timedelta(minutes=1)
    years = t_dec.year.to_numpy()
    quarters = (t_dec.year * 4 + (t_dec.month - 1) // 3).to_numpy()
    cut = idx[int(len(idx) * (1 - HOLDOUT_FRAC))]
    nb = len(FEATURES)
    res = {"asset": asset, "book_from": str(book.index.min()), "decisions_with_book": int(len(dec)),
           "results": [], "book_value": {}}
    for w, stop in BOOK_LABELS:
        lab, net, xi = outcomes(m1, dec, w, stop, asset)
        y = (lab == 1).astype(int)
        known = idx[np.minimum(xi, len(idx) - 1)] + pd.Timedelta(days=1)
        thr = breakeven_p(stop, asset) + MARGIN
        preds = {}
        for kind in ("LOGIT", "LOGIT+BOOK", "LGBM", "LGBM+BOOK"):
            cols = slice(None) if kind.endswith("+BOOK") else slice(0, nb)
            p = np.full(len(dec), np.nan)
            base = np.full(len(dec), np.nan)
            impl = None
            qs = sorted(set(quarters))
            for q in qs[2:]:
                start = pd.Timestamp(year=q // 4, month=(q % 4) * 3 + 1, day=1, tz="UTC")
                tr = np.flatnonzero(known < start)
                te = np.flatnonzero(quarters == q)
                if len(tr) < 15000 or not len(te):
                    continue
                tr = tr[::3]
                m, impl = _model(kind.split("+")[0])
                m.fit(X[tr][:, cols], y[tr])
                p[te] = m.predict_proba(X[te][:, cols])[:, 1]
                base[te] = y[tr].mean()
            preds[kind] = p
            rep = _judge(asset, kind, impl, w, stop, thr, dec, t_dec, years, p, base, y, net, xi, cut,
                         activity_high, len(m1))
            rep["version"] = "scalp-book-1"
            res["results"].append(rep)
        for m_ in ("LOGIT", "LGBM"):
            a, b = preds[m_], preds[m_ + "+BOOK"]
            okk = np.isfinite(a) & np.isfinite(b)
            if okk.sum() < 1000:
                continue
            dif = (a[okk] - y[okk]) ** 2 - (b[okk] - y[okk]) ** 2  # > 0: book helps
            day = t_dec[okk].floor("D").asi8
            u, inv = np.unique(day, return_inverse=True)
            sm, cn = np.bincount(inv, dif, len(u)), np.bincount(inv, None, len(u))
            rng = np.random.default_rng(5)
            boots = [sm[k].sum() / cn[k].sum() for k in (rng.integers(0, len(u), len(u)) for _ in range(2000))]
            ci = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
            res["book_value"][f"{w}m/{stop * 100:.2f}%/{m_}"] = {
                "n": int(okk.sum()), "brier_without": round(float(((a[okk] - y[okk]) ** 2).mean()), 6),
                "brier_with": round(float(((b[okk] - y[okk]) ** 2).mean()), 6),
                "improvement_ci95": [round(ci[0], 7), round(ci[1], 7)], "adds_information": bool(ci[0] > 0)}
    return res
