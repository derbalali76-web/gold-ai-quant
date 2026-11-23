"""frame-divergence-0.1 runner — follows PREREG.md (commit a54d9a1) exactly. Writes results.json."""
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
from goldquant.outlook import MIN_DAILY_BARS, daily_features  # noqa: E402
from goldquant.trend import market_trend  # noqa: E402

CUT = pd.Timestamp("2025-11-15", tz="UTC")
START = {"BTC": "2019-01-01", "ETH": "2019-01-01", "SOL": "2021-01-01", "XAU": "2016-01-01"}
COST = {"BTC": [0.16], "ETH": [0.16], "SOL": [0.22], "XAU": [0.05, 0.0, 0.15]}
REPS, SEED = 10_000, 20261122
D24, D48, D7 = pd.Timedelta(hours=24), pd.Timedelta(hours=48), pd.Timedelta(days=7)


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
    return out[out["n"] == n][["open", "high", "low", "close"]]


def data(asset):
    if asset == "XAU":
        m15 = load("market_data/bars/Dukascopy/XAUUSD/M15")
        h1 = load("market_data/bars/Dukascopy/XAUUSD/H1")
        g = h1.groupby(h1.index.floor("D"))
        d = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                          "close": g["close"].last(), "n": g["close"].size()})
        d = d[d["n"] >= 6][["open", "high", "low", "close"]]
    else:
        m15 = load(f"market_data/crypto/{asset}USDT/15m")
        d = load(f"market_data/crypto/{asset}USDT/1d")
    s = pd.Timestamp(START[asset], tz="UTC") - pd.Timedelta(days=60)   # warm-up for intraday EMAs only
    m15 = m15[(m15.index >= s) & (m15.index < CUT)]
    d = d[d.index + pd.Timedelta(days=1) <= CUT]
    return m15, d


def frames(m15):
    return {"M15": (m15, pd.Timedelta(minutes=15)), "M30": (resample(m15, "30min", 2), pd.Timedelta(minutes=30)),
            "H1": (resample(m15, "1h", 4), pd.Timedelta(hours=1)), "H4": (resample(m15, "4h", 16), pd.Timedelta(hours=4))}


def build(asset):
    m15, d = data(asset)
    ff = {}
    for tf, (df, per) in frames(m15).items():
        f = frame_features(df)
        f.index = f.index + per            # valid at bar close
        ff[tf] = f
    df_ = daily_features(d)
    df_.index = df_.index + pd.Timedelta(days=1)   # valid at day close
    nday = pd.Series(np.arange(1, len(df_) + 1), index=df_.index)
    close15 = m15["close"].copy(); close15.index = close15.index + pd.Timedelta(minutes=15)
    start = pd.Timestamp(START[asset], tz="UTC")
    days = pd.date_range(start, CUT - D7 - pd.Timedelta(days=1), freq="D", tz="UTC")
    if asset == "XAU":
        valid_prev = set((d.index + pd.Timedelta(days=1)))
        days = [t for t in days if t.weekday() < 5 and t in valid_prev]
    hi = m15["high"]
    rows = []
    for t in days:
        if t + D7 >= CUT:
            continue
        k = nday.index.searchsorted(t, side="right") - 1
        if k < 0 or nday.iloc[k] < MIN_DAILY_BARS:
            continue
        fr = df_.iloc[k]
        last = {}
        for tf, f in ff.items():
            j = f.index.searchsorted(t, side="right") - 1
            if j < 0:
                break
            last[tf] = f.iloc[j]
        if len(last) < 4:
            continue
        ht = market_trend(last, "RANGE")["direction"]
        ups = sum(bool(fr["close"] > fr[c]) for c in ("sma20", "sma50", "sma200"))
        wt = "UP" if ups == 3 else "DOWN" if ups == 0 else "SIDEWAYS"
        j0 = close15.index.searchsorted(t, side="right") - 1
        if j0 < 0 or close15.index[j0] < t - pd.Timedelta(hours=72):
            continue
        c0 = float(close15.iloc[j0])
        c24 = float(close15.iloc[close15.index.searchsorted(t + D24, side="right") - 1])
        c7 = float(close15.iloc[close15.index.searchsorted(t + D7, side="right") - 1])
        win = hi[(hi.index >= t) & (hi.index + pd.Timedelta(minutes=15) <= t + D48)]
        atr = float(fr["atr20"])
        lim = c0 + 0.5 * atr
        filled = bool(len(win) and win.max() >= lim)
        g = ("D1" if ht == "UP" and wt == "DOWN" else "D2" if ht == "DOWN" and wt == "UP" else
             "AU" if ht == "UP" and wt == "UP" else "AD" if ht == "DOWN" and wt == "DOWN" else "OTHER")
        rows.append(dict(t=t, g=g, ht=ht, wt=wt, c0=c0, c24=c24, c7=c7, lim=lim, filled=filled,
                         btd=bool(filled and c7 < c0)))
    return pd.DataFrame(rows)


def month_boot(keys, stat_fn, rng):
    months = np.array(sorted(set(keys)))
    groups = {m: np.flatnonzero(keys == m) for m in months}
    out = np.empty(REPS)
    for r in range(REPS):
        pick = rng.choice(months, size=len(months), replace=True)
        idx = np.concatenate([groups[m] for m in pick])
        out[r] = stat_fn(idx)
    return out


def nonoverlap(df):
    keep, nxt = [], None
    for i, t in zip(df.index, df["t"]):
        if nxt is None or t >= nxt:
            keep.append(i); nxt = t + D7
    return df.loc[keep]


def gains(ev, f, bounce):
    f = f / 100
    if bounce:
        return np.where(ev["filled"], ev["lim"] * (1 - f) / (ev["c7"] * (1 + f)) - 1, 0.0)
    return (ev["c0"] * (1 - f) / (ev["c7"] * (1 + f)) - 1).to_numpy()


def holm(ps):
    order = np.argsort(ps); adj = np.empty(len(ps)); run = 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - r) * ps[i])); adj[i] = run
    return adj


def main():
    rng = np.random.default_rng(SEED)
    res = {"study": "frame-divergence-0.1", "prereg_commit": "a54d9a1",
           "prereg_sha256": "89ef19e251f4a4f62d4c969a4da487f90a00769dc67888a17687987bb6e40c21", "assets": {}}
    raw = {"H1": {}, "H2": {}, "H3": {}}
    for a in ("BTC", "ETH", "SOL", "XAU"):
        df = build(a)
        df["month"] = df["t"].dt.strftime("%Y-%m")
        df["r24"] = df["c24"] / df["c0"] - 1; df["r7"] = df["c7"] / df["c0"] - 1
        desc = {}
        for g, sub in df.groupby("g"):
            hd = sub["ht"].map({"UP": 1, "DOWN": -1}).fillna(0); wd = sub["wt"].map({"UP": 1, "DOWN": -1}).fillna(0)
            desc[g] = {"n": int(len(sub)),
                       "hours_hit_24h": None if (hd == 0).all() else round(float((np.sign(sub["r24"])[hd != 0] == hd[hd != 0]).mean()), 3),
                       "week_hit_7d": None if (wd == 0).all() else round(float((np.sign(sub["r7"])[wd != 0] == wd[wd != 0]).mean()), 3),
                       "btd": round(float(sub["btd"].mean()), 3), "mean_r24_pct": round(100 * float(sub["r24"].mean()), 3),
                       "mean_r7_pct": round(100 * float(sub["r7"].mean()), 3)}
        desc["ALL"] = {"n": int(len(df)), "btd": round(float(df["btd"].mean()), 3)}
        A = {"period": [str(df["t"].min().date()), str(df["t"].max().date())], "groups": desc}
        # H1
        isd = (df["g"] == "D1").to_numpy(); btd = df["btd"].to_numpy(float); keys = df["month"].to_numpy()
        def s1(idx):
            m = isd[idx]
            return (btd[idx][m].mean() if m.any() else 0.0) - btd[idx].mean()
        eff = s1(np.arange(len(df)))
        bs = month_boot(keys, s1, rng)
        mid = df["t"].iloc[len(df) // 2]
        halves = [s1(np.flatnonzero((df["t"] < mid).to_numpy())), s1(np.flatnonzero((df["t"] >= mid).to_numpy()))]
        raw["H1"][a] = dict(n=int(isd.sum()), eff=float(eff), p=float((bs <= 0).mean()), halves=halves)
        # H2 / H3
        evd = nonoverlap(df[df["g"] == "D1"]); eva = nonoverlap(df)
        for h, bounce in (("H2", False), ("H3", True)):
            per = {}
            for f in COST[a]:
                gd = gains(evd, f, bounce); ga = gains(eva, f, bounce)
                per[str(f)] = {"mean_d1_pct": round(100 * float(gd.mean()), 3) if len(gd) else None,
                               "mean_all_pct": round(100 * float(ga.mean()), 3), "n_d1": int(len(gd)), "n_all": int(len(ga))}
            f = COST[a][0]; gd = gains(evd, f, bounce); k2 = evd["month"].to_numpy()
            if len(gd):
                b = month_boot(k2, lambda idx: gd[idx].mean(), rng)
                hm = len(gd) // 2
                raw[h][a] = dict(n=int(len(gd)), eff=float(gd.mean()), p=float((b <= 0).mean()),
                                 halves=[float(gd[:hm].mean()) if hm else 0.0, float(gd[hm:].mean())],
                                 all=float(gains(eva, f, bounce).mean()))
            else:
                raw[h][a] = dict(n=0, eff=0.0, p=1.0, halves=[0.0, 0.0], all=0.0)
            A[h] = per
        res["assets"][a] = A
    verdict = {}
    for h in ("H1", "H2", "H3"):
        names = list(raw[h]); adj = holm(np.array([raw[h][a]["p"] for a in names]))
        for a, pa in zip(names, adj):
            r = raw[h][a]
            ok = r["n"] >= 30 and pa < 0.05 and all(x > 0 for x in r["halves"])
            ok = ok and (r["eff"] >= 0.05 if h == "H1" else (r["eff"] > 0 and r["eff"] > r["all"]))
            verdict.setdefault(a, {})[h] = {"n_d1": r["n"], "effect": round(r["eff"] * (100), 3), "unit": "pp" if h == "H1" else "%",
                                           "p_raw": round(r["p"], 4), "p_holm": round(float(pa), 4),
                                           "halves": [round(100 * x, 3) for x in r["halves"]],
                                           "class": "EXPLORATORY_PROMISING" if ok else "NOT_SUPPORTED"}
    res["verdict"] = verdict
    out = Path(__file__).with_name("results.json")
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(verdict, indent=1))


if __name__ == "__main__":
    main()
