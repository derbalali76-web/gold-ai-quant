"""overheat-filters-0.1 runner — follows PREREG.md (commit ba6545d) exactly. Writes results.json."""
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
REPS, SEED = 10_000, 20261124
FLAGS = ["F1", "F2", "F3", "F4", "F5", "F6", "F7"]
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


def flags(df):
    c, h, l = df["close"], df["high"], df["low"]
    pc = c.shift(1)
    atr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
    out = pd.DataFrame(index=df.index)
    out["F1"] = _rsi(c) >= 70
    k = 100 * (c - l.rolling(14).min()) / (h.rolling(14).max() - l.rolling(14).min())
    out["F2"] = k.rolling(3).mean() >= 80
    m, sd = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    out["F3"] = (c - (m - 2 * sd)) / (4 * sd) >= 1
    out["F4"] = (c - c.ewm(span=20, adjust=False).mean()) / atr >= 2
    tp = (h + l + c) / 3
    md = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    out["F5"] = (tp - tp.rolling(20).mean()) / (0.015 * md) >= 100
    out["F6"] = (c - c.shift(24)) / atr >= 3
    return out.fillna(False).astype(bool)


def asof(f, per, t):
    j = f.index.searchsorted(t - per, side="right") - 1   # bar closed at or before t
    return None if j < 0 else f.iloc[j]


def events(asset):
    m15, m30, h1, h4 = data(asset)
    per = {"M15": pd.Timedelta(minutes=15), "M30": pd.Timedelta(minutes=30), "H1": H, "H4": pd.Timedelta(hours=4)}
    ff = {"M15": frame_features(m15), "M30": frame_features(m30), "H1": frame_features(h1), "H4": frame_features(h4)}
    f1, f4 = flags(h1), flags(h4)
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
                        a1, a4 = asof(f1, H, t), asof(f4, per["H4"], t)
                        fl = {k: bool((a1 is not None and a1[k]) or (a4 is not None and a4[k])) for k in FLAGS[:6]}
                        fl["F7"] = sum(fl.values()) >= 3
                        S = sup[0]
                        c24 = float(close15.iloc[close15.index.searchsorted(t + pd.Timedelta(hours=24), side="right") - 1])
                        c72 = float(close15.iloc[close15.index.searchsorted(t + pd.Timedelta(hours=72), side="right") - 1])
                        w = low15[(low15.index >= t) & (low15.index + pd.Timedelta(minutes=15) <= t + pd.Timedelta(hours=72))]
                        filled = bool(len(w) and w.min() <= S)
                        pb1 = S if filled else c72
                        out.append(dict(t=t, **fl,
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
    res = {"study": "overheat-filters-0.1", "prereg_commit": "ba6545d",
           "prereg_sha256": "2dfcad8867742d994432d90db8f24196d260e65d1b888e6f39c719a9dcd591fa", "assets": {}}
    raw = {"B1": {}, "B2": {}}
    for a in ("BTC", "ETH", "SOL", "XAU"):
        df = events(a)
        df["month"] = df["t"].dt.strftime("%Y-%m")
        A = {"period": [str(df["t"].min()), str(df["t"].max())], "buy_now_events": int(len(df)), "flags": {}}
        for f in FLAGS:
            on, off = df[df[f]], df[~df[f]]
            A["flags"][f] = {"n_on": int(len(on)), "on_r24_pct": round(100 * on["r24"].mean(), 3) if len(on) else None,
                             "off_r24_pct": round(100 * off["r24"].mean(), 3), "B1_fill_on": round(float(on["filled"].mean()), 3) if len(on) else None}
            for P, col in (("B1", "g1"), ("B2", "g2")):
                v = on[col].to_numpy(); hm = len(v) // 2
                raw[P][(f, a)] = dict(n=len(v), eff=float(v.mean()) if len(v) else 0.0,
                                      p=boot(v, on["month"].to_numpy(), rng) if len(v) >= 2 else 1.0,
                                      halves=[float(v[:hm].mean()) if hm else 0.0, float(v[hm:].mean()) if len(v) else 0.0],
                                      off=float(off[col].mean()))
        res["assets"][a] = A
    verdict = {}
    for P in ("B1", "B2"):
        keys = list(raw[P]); adj = holm(np.array([raw[P][k]["p"] for k in keys]))
        for (f, a), pa in zip(keys, adj):
            r = raw[P][(f, a)]
            ok = r["n"] >= 30 and pa < 0.05 and r["eff"] > 0 and all(x > 0 for x in r["halves"]) and r["off"] < r["eff"]
            verdict.setdefault(P, {}).setdefault(f, {})[a] = {
                "n_on": r["n"], "mean_gain_pct": round(100 * r["eff"], 3), "off_gain_pct": round(100 * r["off"], 3),
                "p_raw": round(r["p"], 4), "p_holm": round(float(pa), 4), "halves_pct": [round(100 * x, 3) for x in r["halves"]],
                "class": "EXPLORATORY_PROMISING" if ok else "NOT_SUPPORTED"}
    res["verdict"] = verdict
    cand = []
    for P in verdict:
        for f, per in verdict[P].items():
            q = [a for a, v in per.items() if v["class"] == "EXPLORATORY_PROMISING"]
            if len(q) >= 2 and all(v["mean_gain_pct"] >= 0 for v in per.values()):
                cand.append((len(q), sum(v["mean_gain_pct"] for v in per.values()), P, f))
    cand.sort(reverse=True)
    res["app_rule"] = {"adopt": None if not cand else {"policy": cand[0][2], "flag": cand[0][3]}}
    Path(__file__).with_name("results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    summ = {P: {f: {a: (v["mean_gain_pct"], v["n_on"], v["p_holm"], v["class"][:3]) for a, v in per.items()}
                for f, per in verdict[P].items()} for P in verdict}
    print(json.dumps({"summary": summ, "app_rule": res["app_rule"]}, indent=0))


if __name__ == "__main__":
    main()
