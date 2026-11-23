"""rsi-cooldown-0.1 runner — follows PREREG.md (commit 6f39a2e) exactly. Writes results.json."""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from goldquant.features import frame_features  # noqa: E402
from goldquant.levels import compute_levels  # noqa: E402
from goldquant.outlook import _rsi  # noqa: E402
from goldquant.trend import market_trend  # noqa: E402

CUT = pd.Timestamp("2025-11-15", tz="UTC")
REPS, SEED = 10_000, 20261123
H = pd.Timedelta(hours=1)


def load(d):
    fs = sorted(glob.glob(str(ROOT / d / "*.csv.gz")))
    df = pd.concat(pd.read_csv(f) for f in fs)
    df.index = pd.to_datetime(df["open_time"], format="ISO8601", utc=True)
    df = df[["open", "high", "low", "close"]].astype(float).sort_index()
    return df[~df.index.duplicated()]


def resample(m15, rule, n):
    g = m15.resample(rule, label="left", closed="left")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "n": g["close"].size()})
    return out[out["n"] >= n][["open", "high", "low", "close"]] if n == 0 else out[out["n"] == n][["open", "high", "low", "close"]]


def data(asset):
    if asset == "XAU":
        m15 = load("market_data/bars/Dukascopy/XAUUSD/M15")
        h1 = load("market_data/bars/Dukascopy/XAUUSD/H1")
        h4 = h1.resample("4h", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    else:
        m15 = load(f"market_data/crypto/{asset}USDT/15m")
        h1 = resample(m15, "1h", 4)
        h4 = resample(m15, "4h", 16)
    m30 = resample(m15, "30min", 2)
    keep = lambda df: df[df.index < CUT]  # noqa: E731
    return keep(m15), keep(m30), keep(h1), keep(h4)


def asof(f, per, t):
    j = f.index.searchsorted(t - per, side="right") - 1   # bar closed at or before t
    return None if j < 0 else f.iloc[j]


def events(asset):
    m15, m30, h1, h4 = data(asset)
    per = {"M15": pd.Timedelta(minutes=15), "M30": pd.Timedelta(minutes=30), "H1": H, "H4": pd.Timedelta(hours=4)}
    ff = {"M15": frame_features(m15), "M30": frame_features(m30), "H1": frame_features(h1), "H4": frame_features(h4)}
    r1, r4 = _rsi(h1["close"]), _rsi(h4["close"])
    close15 = m15["close"].copy(); close15.index = close15.index + pd.Timedelta(minutes=15)
    low15 = m15["low"]
    start = (max(h1.index[0] + pd.Timedelta(days=730), m15.index[0] + pd.Timedelta(days=10))).ceil("D")
    t, out, n_buy = start, [], 0
    while t + pd.Timedelta(hours=72) < CUT:
        step = pd.Timedelta(hours=4)
        j0 = close15.index.searchsorted(t, side="right") - 1
        ok = j0 >= 0 and close15.index[j0] > t - H
        if ok:
            p0 = float(close15.iloc[j0])
            last = {tf: asof(ff[tf], per[tf], t) for tf in ff}
            if all(v is not None for v in last.values()) and market_trend(last, "RANGE")["direction"] == "UP":
                bars = {"M15": m15[(m15.index >= t - pd.Timedelta(days=12)) & (m15.index < t)],
                        "H1": h1[(h1.index >= t - pd.Timedelta(days=70)) & (h1.index < t)],
                        "H4": h4[(h4.index >= t - pd.Timedelta(days=210)) & (h4.index < t)]}
                if not bars["M15"].empty and len(bars["H1"]) >= 200:
                    lv = compute_levels(bars, t, p0)
                    sup = sorted([x["price"] for x in lv["supports"] if x["price"] < p0], reverse=True)
                    res = sorted([x["price"] for x in lv["resistances"] if x["price"] > p0])
                    if sup and res and (p0 - sup[0]) / (res[0] - sup[0]) <= 0.66:
                        a1, a4 = asof(r1, H, t), asof(r4, per["H4"], t)
                        hot = bool((a1 is not None and a1 >= 70) or (a4 is not None and a4 >= 70))
                        S = sup[0]
                        c24 = float(close15.iloc[close15.index.searchsorted(t + pd.Timedelta(hours=24), side="right") - 1])
                        c72 = float(close15.iloc[close15.index.searchsorted(t + pd.Timedelta(hours=72), side="right") - 1])
                        w = low15[(low15.index >= t) & (low15.index + pd.Timedelta(minutes=15) <= t + pd.Timedelta(hours=72))]
                        filled = bool(len(w) and w.min() <= S)
                        pb1 = S if filled else c72
                        out.append(dict(t=t, hot=hot, rsi1=None if a1 is None else float(a1), rsi4=None if a4 is None else float(a4),
                                        p0=p0, g1=p0 / pb1 - 1, g2=p0 / c24 - 1, r24=c24 / p0 - 1, r72=c72 / p0 - 1, filled=filled))
                        step = pd.Timedelta(hours=72)
        t += step
    return pd.DataFrame(out)


def boot(vals, months, rng):
    ms = np.array(sorted(set(months))); g = {m: np.flatnonzero(months == m) for m in ms}
    res = np.empty(REPS)
    for r in range(REPS):
        idx = np.concatenate([g[m] for m in rng.choice(ms, len(ms))])
        res[r] = vals[idx].mean()
    return float((res <= 0).mean())


def holm(ps):
    order = np.argsort(ps); adj = np.empty(len(ps)); run = 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - r) * ps[i])); adj[i] = run
    return adj


def main():
    rng = np.random.default_rng(SEED)
    res = {"study": "rsi-cooldown-0.1", "prereg_commit": "6f39a2e",
           "prereg_sha256": "285ea91bbcb8549d9ce99298fabcc9347a3e1083546efbe97392ba943553fa00", "assets": {}}
    raw = {"H1": {}, "H2": {}}
    for a in ("BTC", "ETH", "SOL", "XAU"):
        df = events(a)
        df["month"] = df["t"].dt.strftime("%Y-%m")
        hot, cold = df[df["hot"]], df[~df["hot"]]
        A = {"period": [str(df["t"].min()), str(df["t"].max())], "buy_now_events": int(len(df)),
             "hot": int(len(hot)), "not_hot": int(len(cold))}
        for name, sub in (("hot", hot), ("not_hot", cold)):
            A[name + "_desc"] = {"mean_r24_pct": round(100 * sub["r24"].mean(), 3), "mean_r72_pct": round(100 * sub["r72"].mean(), 3),
                                 "B1_gain_pct": round(100 * sub["g1"].mean(), 3), "B2_gain_pct": round(100 * sub["g2"].mean(), 3),
                                 "B1_fill_rate": round(float(sub["filled"].mean()), 3)}
        res["assets"][a] = A
        for h, col in (("H1", "g1"), ("H2", "g2")):
            v = hot[col].to_numpy(); hm = len(v) // 2
            raw[h][a] = dict(n=len(v), eff=float(v.mean()) if len(v) else 0.0,
                             p=boot(v, hot["month"].to_numpy(), rng) if len(v) else 1.0,
                             halves=[float(v[:hm].mean()) if hm else 0.0, float(v[hm:].mean()) if len(v) else 0.0],
                             cold=float(cold[col].mean()))
    verdict = {}
    for h in ("H1", "H2"):
        names = list(raw[h]); adj = holm(np.array([raw[h][a]["p"] for a in names]))
        for a, pa in zip(names, adj):
            r = raw[h][a]
            ok = r["n"] >= 30 and pa < 0.05 and r["eff"] > 0 and all(x > 0 for x in r["halves"]) and r["cold"] < r["eff"]
            verdict.setdefault(a, {})[h] = {"n_hot": r["n"], "mean_gain_pct": round(100 * r["eff"], 3),
                                           "not_hot_gain_pct": round(100 * r["cold"], 3), "p_raw": round(r["p"], 4),
                                           "p_holm": round(float(pa), 4), "halves_pct": [round(100 * x, 3) for x in r["halves"]],
                                           "class": "EXPLORATORY_PROMISING" if ok else "NOT_SUPPORTED"}
    res["verdict"] = verdict
    promising = {h: [a for a in verdict if verdict[a][h]["class"] == "EXPLORATORY_PROMISING"] for h in ("H1", "H2")}
    neg = {h: [a for a in verdict if verdict[a][h]["mean_gain_pct"] < 0] for h in ("H1", "H2")}
    res["app_rule"] = {"add_cooldown": any(len(promising[h]) >= 2 and not neg[h] for h in ("H1", "H2")),
                       "promising": promising, "negative": neg}
    Path(__file__).with_name("results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({"assets": res["assets"], "verdict": verdict, "app_rule": res["app_rule"]}, indent=1))


if __name__ == "__main__":
    main()
