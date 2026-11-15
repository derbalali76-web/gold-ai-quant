"""Multi-asset tournament for the WEEK and MONTH horizons (research; nothing here issues a recommendation by itself).

PRE-REGISTERED 2026-11-15, BEFORE any result was seen.

Why: one asset gives ~3,000 daily samples, too few for anything but a very simple model. Training ONE model on many
markets (gold, FX, oil, equity indices, bonds, crypto) multiplies the samples; asset-agnostic, volatility-scaled
features let what is learned on one market apply to another. Positioning of large speculators (CFTC COT) is added
where a futures market exists.

Panel     daily closes (UTC day): XAU, BTC, ETH, SOL (own stores); EUR, JPY, GBP, AUD, CAD, CHF vs USD, WTI, Brent,
          Nasdaq Composite (FRED, no key); S&P 500 index, US dollar index, US 10-y T-bond (Dukascopy).
Features  (all known at the day's close; vol = 20-day stdev of daily log returns)
          r1, r5, r21, r63, r126, r252 / (vol * sqrt(n)); close vs MA20/50/200 / vol; RSI14; vol20/vol252;
          position in the 20- and 63-day close range; COT: speculators' net % of open interest, its 3-year z-score and
          4-week change — usable only from the Monday after the Friday release (no look-ahead); 0 + flag if none.
Target    sign of the return over the next H calendar days (WEEK H=7, MONTH H=30).
Models    POOLED_LOGIT  logistic regression (C=0.05) on all assets
          POOLED_HGB    gradient-boosted trees (depth 3, 200 iterations, lr 0.05, min leaf 200, l2 1.0) on all assets
          SINGLE_LOGIT  the same logistic regression trained on the target asset only (reference, not a candidate)
Training  expanding window, re-fitted every calendar year from 2012; a training row is used only if its outcome was
          known before the test year starts (purge = H days). Last 20 % of time = final holdout.
Rule      long if P(up) >= 0.55; short if P(up) <= 0.45 only where shorting is normal (gold CFD, FX, indices, oil,
          bonds; NOT crypto spot); otherwise flat. Every day is a decision; trades overlap, so confidence intervals use
          a block bootstrap with blocks of H days.
Judged on XAU, BTC, ETH, SOL (2 models x 2 horizons x 4 assets = 16 tests -> 99.7 % confidence). Qualifies only if:
          >= 50 non-overlapping trade-equivalents; average net CI above zero; both halves positive; holdout positive;
          beats ALWAYS-LONG on the same days (CI above zero); beats SINGLE_LOGIT on average; Brier better than the
          training base rate (calibration) on the target asset.
Correction (declared after the first run, 2026-11-15): for buy-only assets "always long on the same days" equals the
rule itself, so that check could never pass. The baseline that tests TIMING is always-long on EVERY day; it is now
required for all assets (and the same-days check stays for assets that can be shorted). No rule, threshold or model
changed.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

VERSION = "pooled-1"
HORIZONS = {"WEEK": 7, "MONTH": 30}
MODELS = ("POOLED_LOGIT", "POOLED_HGB")
TARGETS = ("XAU", "BTC", "ETH", "SOL")
THRESH = 0.55
CI_LEVEL = 99.7
FIRST_TEST_YEAR = 2012
HOLDOUT_FRAC = 0.2
COST = {"XAU": 0.0004, "BTC": 0.0022, "ETH": 0.0022, "SOL": 0.0025, "EUR": 0.0002, "JPY": 0.0002, "GBP": 0.0002,
        "AUD": 0.0002, "CAD": 0.0002, "CHF": 0.0002, "WTI": 0.0006, "BRENT": 0.0006, "NASDAQ": 0.0003,
        "SPX": 0.0003, "USDX": 0.0002, "TBOND": 0.0002}
LONG_ONLY = {"BTC", "ETH", "SOL"}
# FRED daily series -> asset name (price of the asset in USD; JPY/CAD/CHF are quoted per USD, so inverted)
FRED_ASSETS = {"DEXUSEU": ("EUR", False), "DEXJPUS": ("JPY", True), "DEXUSUK": ("GBP", False),
               "DEXUSAL": ("AUD", False), "DEXCAUS": ("CAD", True), "DEXSZUS": ("CHF", True),
               "DCOILWTICO": ("WTI", False), "DCOILBRENTEU": ("BRENT", False), "NASDAQCOM": ("NASDAQ", False)}
DUKA_ASSETS = {"USA500IDXUSD": "SPX", "DOLLARIDXUSD": "USDX", "USTBONDTRUSD": "TBOND"}
# CFTC COT: (dataset, contract code). Disaggregated = managed money; TFF = leveraged funds.
COT_DISAGG, COT_TFF = "72hh-3qpy", "gpe5-46if"
COT_MAP = {"XAU": (COT_DISAGG, "088691"), "WTI": (COT_DISAGG, "067651"), "EUR": (COT_TFF, "099741"),
           "JPY": (COT_TFF, "097741"), "GBP": (COT_TFF, "096742"), "AUD": (COT_TFF, "232741"),
           "CAD": (COT_TFF, "090741"), "CHF": (COT_TFF, "092741"), "SPX": (COT_TFF, "13874A"),
           "NASDAQ": (COT_TFF, "209742"), "TBOND": (COT_TFF, "020601"), "USDX": (COT_TFF, "098662"),
           "BTC": (COT_TFF, "133741"), "ETH": (COT_TFF, "146021")}
BASE_FEATURES = ["r1", "r5", "r21", "r63", "r126", "r252", "ma20", "ma50", "ma200", "rsi", "volr", "rp20", "rp63"]
COT_FEATURES = ["cot_net", "cot_z", "cot_chg4", "has_cot"]
FEATURES = BASE_FEATURES + COT_FEATURES


# ---------------------------------------------------------------- COT parsing (Socrata JSON)
def parse_cot_rows(rows: list) -> pd.DataFrame:
    """Speculators' net position as a share of open interest, with the conservative 'usable from' time."""
    out = []
    for r in rows:
        try:
            d = pd.Timestamp(r["report_date_as_yyyy_mm_dd"]).normalize()
            if "m_money_positions_long_all" in r:
                lo, sh = float(r["m_money_positions_long_all"]), float(r["m_money_positions_short_all"])
            else:
                lk = next(k for k in r if k.startswith("lev_money_positions_long"))
                sk = next(k for k in r if k.startswith("lev_money_positions_short"))
                lo, sh = float(r[lk]), float(r[sk])
            oi = float(r["open_interest_all"])
        except (KeyError, ValueError, StopIteration):
            continue
        if oi <= 0:
            continue
        d = d.tz_localize("UTC") if d.tzinfo is None else d.tz_convert("UTC")
        # as of Tuesday, released Friday 15:30 New York -> used from the next Monday's close onwards
        out.append({"report": d, "usable": d + pd.Timedelta(days=6), "net": (lo - sh) / oi})
    if not out:
        return pd.DataFrame(columns=["report", "usable", "net"])
    return pd.DataFrame(out).drop_duplicates("report").sort_values("report").reset_index(drop=True)


def cot_features(index: pd.DatetimeIndex, cot: Optional[pd.DataFrame]) -> pd.DataFrame:
    f = pd.DataFrame(0.0, index=index, columns=COT_FEATURES)
    if cot is None or len(cot) < 60:
        return f
    c = cot.copy()
    c["z"] = (c["net"] - c["net"].rolling(156, min_periods=52).mean()) / c["net"].rolling(156, min_periods=52).std()
    c["chg4"] = c["net"].diff(4)
    m = pd.merge_asof(pd.DataFrame({"t": index}), c[["usable", "net", "z", "chg4"]].rename(columns={"usable": "t"}),
                      on="t", direction="backward")
    ok = m["net"].notna().to_numpy() & m["z"].notna().to_numpy()
    f.loc[ok, "cot_net"] = m["net"].to_numpy()[ok]
    f.loc[ok, "cot_z"] = m["z"].to_numpy()[ok]
    f.loc[ok, "cot_chg4"] = m["chg4"].fillna(0).to_numpy()[ok]
    f.loc[ok, "has_cot"] = 1.0
    return f


# ---------------------------------------------------------------- features / labels per asset
def asset_features(close: pd.Series, cot: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    c = close.astype(float)
    lr = np.log(c).diff()
    vol = lr.rolling(20, min_periods=15).std()
    f = pd.DataFrame(index=c.index)
    for n in (1, 5, 21, 63, 126, 252):
        f[f"r{n}"] = np.log(c / c.shift(n)) / (vol * np.sqrt(n))
    for n in (20, 50, 200):
        f[f"ma{n}"] = (np.log(c) - np.log(c.rolling(n).mean())) / vol
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    f["rsi"] = (100 - 100 / (1 + up / dn.replace(0, np.nan))) / 100 - 0.5
    f["volr"] = np.log(vol / lr.rolling(252, min_periods=120).std())
    for n in (20, 63):
        lo, hi = c.rolling(n).min(), c.rolling(n).max()
        f[f"rp{n}"] = (c - lo) / (hi - lo).replace(0, np.nan) - 0.5
    f = f.join(cot_features(c.index, cot))
    return f.replace([np.inf, -np.inf], np.nan)


def forward_return(close: pd.Series, days: int) -> pd.Series:
    """Return from this close to the last close at or before t + days (calendar); NaN if that is not known yet."""
    t = close.index
    target = t + pd.Timedelta(days=days)
    pos = np.searchsorted(t.asi8, target.asi8, side="right") - 1
    fr = close.to_numpy(float)[np.clip(pos, 0, len(t) - 1)] / close.to_numpy(float) - 1
    known = target <= t[-1]
    fr[~known] = np.nan
    return pd.Series(fr, index=t)


def build_panel(closes: dict, cots: dict, days: int) -> pd.DataFrame:
    parts = []
    for a, s in closes.items():
        s = s.dropna()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        if len(s) < 400:
            continue
        f = asset_features(s, cots.get(a))
        f["fwd"] = forward_return(s, days)
        f["asset"] = a
        f["end"] = s.index + pd.Timedelta(days=days)
        parts.append(f)
    p = pd.concat(parts)
    p = p.dropna(subset=BASE_FEATURES)
    return p


# ---------------------------------------------------------------- models
def _model(kind: str):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if kind == "POOLED_HGB":
        return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=200,
                                              l2_regularization=1.0, random_state=7)
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=2000))


def walk_forward_predictions(panel: pd.DataFrame, days: int, kinds=MODELS + ("SINGLE_LOGIT",),
                             targets=TARGETS) -> pd.DataFrame:
    """Out-of-sample P(up) for every (asset, day) of the target assets, per model, fitted once per calendar year."""
    panel = panel.copy()
    panel["y"] = (panel["fwd"] > 0).astype(float)
    lab = panel.dropna(subset=["fwd"])
    years = sorted(set(panel.index.year))
    out = []
    for yr in [y for y in years if y >= FIRST_TEST_YEAR]:
        start = pd.Timestamp(f"{yr}-01-01", tz="UTC")
        stop = pd.Timestamp(f"{yr + 1}-01-01", tz="UTC")
        tr = lab[lab["end"] < start]
        te = panel[(panel.index >= start) & (panel.index < stop) & panel["asset"].isin(targets)]
        if len(tr) < 2000 or not len(te):
            continue
        row = te[["asset", "fwd"]].copy()
        X = tr[FEATURES].fillna(0.0).to_numpy()
        Xt = te[FEATURES].fillna(0.0).to_numpy()
        for k in kinds:
            if k == "SINGLE_LOGIT":
                p = np.full(len(te), np.nan)
                for a in te["asset"].unique():
                    ta = tr[tr["asset"] == a]
                    msk = (te["asset"] == a).to_numpy()
                    if len(ta) < 500 or ta["y"].nunique() < 2:
                        continue
                    m = _model("POOLED_LOGIT").fit(ta[BASE_FEATURES + COT_FEATURES].fillna(0.0).to_numpy(), ta["y"])
                    p[msk] = m.predict_proba(Xt[msk])[:, 1]
                row[k] = p
            else:
                m = _model(k).fit(X, tr["y"].to_numpy())
                row[k] = m.predict_proba(Xt)[:, 1]
        base = {a: float(tr[tr["asset"] == a]["y"].mean()) if (tr["asset"] == a).sum() else float(tr["y"].mean())
                for a in te["asset"].unique()}
        row["base_rate"] = te["asset"].map(base).to_numpy()
        out.append(row)
    return pd.concat(out) if out else pd.DataFrame()


# ---------------------------------------------------------------- judging
def _block_boot(x: np.ndarray, block: int, level=CI_LEVEL, n=2000, seed=7, y: Optional[np.ndarray] = None):
    if len(x) < 2 * block:
        return None
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(len(x) / block))
    starts_max = len(x) - block
    res = []
    for _ in range(n):
        s = rng.integers(0, starts_max + 1, nb)
        idx = (s[:, None] + np.arange(block)[None, :]).ravel()[:len(x)]
        res.append(float(x[idx].mean() - (y[idx].mean() if y is not None else 0.0)))
    a = (100 - level) / 2
    return [round(float(np.percentile(res, a)) * 100, 4), round(float(np.percentile(res, 100 - a)) * 100, 4)]


def _boot_means(x: np.ndarray, block: int, n=2000, seed=7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(len(x) / block))
    out = np.empty(n)
    for i in range(n):
        s = rng.integers(0, max(1, len(x) - block + 1), nb)
        idx = (s[:, None] + np.arange(block)[None, :]).ravel()[:len(x)]
        out[i] = x[np.clip(idx, 0, len(x) - 1)].mean()
    return out


def judge(preds: pd.DataFrame, asset: str, model: str, days: int) -> dict:
    d = preds[(preds["asset"] == asset)].dropna(subset=["fwd", model]).sort_index()
    rep = {"asset": asset, "model": model, "horizon_days": days, "version": VERSION, "qualified": False}
    if len(d) < 200:
        rep["reason"] = "insufficient data"
        return rep
    p, fwd = d[model].to_numpy(), d["fwd"].to_numpy()
    cost = COST.get(asset, 0.0005)
    side = np.where(p >= THRESH, 1, np.where((p <= 1 - THRESH) & (asset not in LONG_ONLY), -1, 0))
    take = side != 0
    net = side[take] * fwd[take] - cost
    long_all = fwd[take] - cost  # always-long on the same days
    t_idx = d.index[take]
    rep.update({"period": f"{d.index[0].date()} -> {d.index[-1].date()}", "days": int(len(d)),
                "trades": int(take.sum()), "long_share": round(float((side[take] == 1).mean()), 3) if take.any() else None,
                "trade_equivalents": round(float(take.sum()) / days * (5 / 7 if asset not in LONG_ONLY else 1), 1)})
    if take.sum() < 2 * days:
        rep["reason"] = "too few trades"
        return rep
    block = days if asset in LONG_ONLY else max(1, int(days * 5 / 7))
    rep["avg_net_pct"] = round(float(net.mean()) * 100, 4)
    rep["avg_net_ci"] = _block_boot(net, block)
    rep["always_long_avg_pct"] = round(float(long_all.mean()) * 100, 4)
    rep["edge_vs_long_ci"] = _block_boot(net, block, y=long_all) if asset not in LONG_ONLY else None
    all_long = fwd - cost  # always long on every decision day
    rep["always_long_all_days_pct"] = round(float(all_long.mean()) * 100, 4)
    b1 = _boot_means(net, block)
    b2 = _boot_means(all_long, block, seed=8)
    a_ = (100 - CI_LEVEL) / 2
    rep["edge_vs_long_all_days_ci"] = [round(float(np.percentile(b1 - b2, a_)) * 100, 4),
                                       round(float(np.percentile(b1 - b2, 100 - a_)) * 100, 4)]
    rep["win_rate"] = round(float((net > 0).mean()), 4)
    half = len(net) // 2
    rep["halves_pct"] = [round(float(net[:half].mean()) * 100, 4), round(float(net[half:].mean()) * 100, 4)]
    cut = d.index[int(len(d) * (1 - HOLDOUT_FRAC))]
    ho = net[t_idx >= cut]
    rep["holdout_trades"] = int(len(ho))
    rep["holdout_avg_pct"] = round(float(ho.mean()) * 100, 4) if len(ho) else None
    # equity on non-overlapping trades (every block-th decision day) -> honest drawdown
    step = net[::block]
    eq = np.cumsum(step)
    rep["max_drawdown_pct"] = round(float(np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq])) * 100, 2)
    rep["total_net_nonoverlap_pct"] = round(float(eq[-1]) * 100, 2)
    # reference: single-asset model with the same rule
    single = None
    if "SINGLE_LOGIT" in d.columns and d["SINGLE_LOGIT"].notna().sum() > 100:
        ps = d["SINGLE_LOGIT"].to_numpy()
        ss = np.where(ps >= THRESH, 1, np.where((ps <= 1 - THRESH) & (asset not in LONG_ONLY), -1, 0))
        ok = (ss != 0) & np.isfinite(ps)
        single = float((ss[ok] * fwd[ok] - cost).mean()) if ok.any() else None
    rep["single_asset_avg_pct"] = round(single * 100, 4) if single is not None else None
    y = (fwd > 0).astype(float)
    brier = float(np.mean((p - y) ** 2))
    brier_base = float(np.mean((d["base_rate"].to_numpy() - y) ** 2))
    rep["brier"], rep["brier_base"] = round(brier, 5), round(brier_base, 5)
    ck = {
        "at least 50 trade-equivalents": rep["trade_equivalents"] >= 50,
        "average net CI above zero": bool(rep["avg_net_ci"] and rep["avg_net_ci"][0] > 0),
        "both halves positive": min(rep["halves_pct"]) > 0,
        "final holdout positive": rep["holdout_trades"] >= days and (rep["holdout_avg_pct"] or 0) > 0,
        "beats always-long on the same days (CI)": asset in LONG_ONLY or bool(rep["edge_vs_long_ci"]
                                                                              and rep["edge_vs_long_ci"][0] > 0),
        "beats always-long on every day (CI)": rep["edge_vs_long_all_days_ci"][0] > 0,
        "beats single-asset model": single is None or float(net.mean()) > single,
        "calibrated (Brier < base rate)": brier < brier_base,
    }
    rep["checks"] = ck
    rep["qualified"] = all(ck.values())
    rep["reason"] = "qualified" if rep["qualified"] else "failed: " + "; ".join(k for k, v in ck.items() if not v)
    return rep


def tournament(closes: dict, cots: dict) -> dict:
    out = {"version": VERSION, "assets_in_panel": sorted(closes), "cot_assets": sorted(k for k, v in cots.items()
                                                                                       if v is not None and len(v)),
           "results": []}
    for hz, days in HORIZONS.items():
        panel = build_panel(closes, cots, days)
        out.setdefault("panel_rows", {})[hz] = int(len(panel))
        preds = walk_forward_predictions(panel, days)
        if preds.empty:
            continue
        for a in TARGETS:
            for m in MODELS:
                r = judge(preds, a, m, days)
                r["horizon"] = hz
                out["results"].append(r)
    return out
