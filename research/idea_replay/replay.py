#!/usr/bin/env python3
"""idea-replay-0.1: replay the «ماذا أفعل؟» rule on history (see PREREG.md, written before this ran).

    python research/idea_replay/replay.py [--assets XAU,BTC,ETH,SOL] [--out research/idea_replay]
Writes samples.jsonl (one line per scored idea) and report.json.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from goldquant import crypto_store as CS  # noqa: E402
from goldquant.features import frame_features  # noqa: E402
from goldquant.levels import compute_levels  # noqa: E402
from goldquant.trend import market_trend  # noqa: E402

spec = importlib.util.spec_from_file_location("ideas", ROOT / "ledger" / "ideas.py")
I = importlib.util.module_from_spec(spec); sys.modules["ideas"] = I; spec.loader.exec_module(I)  # noqa: E702

START = pd.Timestamp("2024-12-01T00:00:00Z")
SPLIT = pd.Timestamp("2026-06-01T00:00:00Z")
STEP_H = 4
MIN_BARS = {"M15": 600, "M30": 300, "H1": 200, "H4": 100}
MINS = {"M15": 15, "M30": 30, "H1": 60, "H4": 240}
SYM = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
AGG = {"open": "first", "high": "max", "low": "min", "close": "last"}


def _rs(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df[["open", "high", "low", "close"]].resample(rule, label="left", closed="left").agg(AGG).dropna()


def load(asset: str) -> dict:
    if asset == "XAU":
        base = ROOT / "market_data" / "bars" / "Dukascopy" / "XAUUSD"
        def rd(tf):
            fs = sorted((base / tf).glob("*.csv.gz"))
            df = pd.concat(pd.read_csv(f, index_col=0, parse_dates=True) for f in fs)
            df.index = pd.to_datetime(df.index, utc=True)
            return df[~df.index.duplicated(keep="last")].sort_index()[["open", "high", "low", "close"]]
        m15, h1, h4 = rd("M15"), rd("H1"), rd("H4")
    else:
        m15 = CS.load_bars(ROOT / "market_data", SYM[asset], "15m")[["open", "high", "low", "close"]]
        h1 = CS.load_bars(ROOT / "market_data", SYM[asset], "1h")[["open", "high", "low", "close"]]
        h4 = _rs(h1, "4h")
    return {"M15": m15, "M30": _rs(m15, "30min"), "H1": h1, "H4": h4}


def prep(asset: str) -> dict:
    b = load(asset)
    feats = {tf: frame_features(df) for tf, df in b.items()}
    # bar open time -> close time, for "closed by t" lookups
    close = {tf: df.index + pd.Timedelta(minutes=MINS[tf]) for tf, df in b.items()}
    return {"bars": b, "feats": feats, "close": close}


def at(P: dict, t: pd.Timestamp):
    """(trend, price, levels dict) using only bars closed by t, or None."""
    b, F, C = P["bars"], P["feats"], P["close"]
    idx = {tf: int(C[tf].searchsorted(t, side="right")) for tf in b}
    if any(idx[tf] < MIN_BARS[tf] for tf in b):
        return None
    if (t - C["H1"][idx["H1"] - 1]) > pd.Timedelta(hours=2):
        return None  # market closed / gap
    rows = {tf: F[tf].iloc[idx[tf] - 1] for tf in b}
    tr = market_trend(rows, "RANGE")["direction"]
    price = float(b["M15"]["close"].iloc[idx["M15"] - 1])
    sub = {tf: b[tf].iloc[max(0, idx[tf] - 3000):idx[tf]] for tf in ("M15", "H1", "H4")}
    lv = compute_levels(sub, t.to_pydatetime(), price)
    return tr, price, lv


def h1_after(P: dict, t: pd.Timestamp) -> list:
    h1 = P["bars"]["H1"]
    m = (h1.index >= t) & (h1.index + pd.Timedelta(hours=1) <= t + pd.Timedelta(hours=I.HORIZONS["HOURS"]))
    s = h1[m]
    return [[ts.strftime("%Y-%m-%dT%H:%M:%SZ"), float(r.open), float(r.high), float(r.low), float(r.close)]
            for ts, r in s.iterrows()]


def run(assets: list[str], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    P = {a: prep(a) for a in sorted(set(assets) | {"BTC"})}
    end = min(P[a]["close"]["H1"][-1] for a in assets) - pd.Timedelta(hours=I.HORIZONS["HOURS"])
    times = pd.date_range(START, end, freq=f"{STEP_H}h")
    rows = []
    btc_cache = {}
    for n, t in enumerate(times):
        if t not in btc_cache:
            r = at(P["BTC"], t)
            btc_cache[t] = r[0] if r else None
        for a in assets:
            r = at(P[a], t) if a != "BTC" else None
            if a == "BTC":
                r = at(P["BTC"], t)
            if r is None:
                continue
            tr, price, lv = r
            sup = [x["price"] for x in lv["supports"]][:2]
            res = [x["price"] for x in lv["resistances"]][:2]
            atr = lv.get("atr_h1") or None
            bars = h1_after(P[a], t)
            if len(bars) < I.HORIZONS["HOURS"] - 2:
                continue
            for mode in ("cash", "holder"):
                i = I.decide(tr, price, sup, res, mode == "holder", a, atr, btc_cache[t])
                if i["kind"] == "NONE":
                    continue
                d = {"asset": a, "horizon": "HOURS", "mode": mode, "price": price, **i}
                s = I.score(d, bars)
                if s is None:
                    continue
                row = {"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "asset": a, "mode": mode, "kind": i["kind"],
                       "trend": tr, "btc_trend": btc_cache[t], "price": price, "edge": s["edge_pct"],
                       "idea_pct": s["idea_pct"], "success": s["success"]}
                if i.get("note") == "BTC_DOWN":
                    sh = I.decide(tr, price, sup, res, mode == "holder", a, atr, None)
                    ss = I.score({"asset": a, "horizon": "HOURS", "mode": mode, "price": price, **sh}, bars)
                    if ss is not None:
                        row["shadow_kind"], row["shadow_edge"], row["shadow_idea_pct"] = sh["kind"], ss["edge_pct"], ss["idea_pct"]
                rows.append(row)
        if n % 200 == 0:
            print(f"{t} {n}/{len(times)} rows={len(rows)}", flush=True)
    with (out / "samples.jsonl").open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    (out / "report.json").write_text(json.dumps(report(rows), indent=1, ensure_ascii=False) + "\n")


def boot_ci(df: pd.DataFrame, col: str, seed: int = 0, n_boot: int = 2000) -> tuple[float, float]:
    """Moving-block bootstrap of the mean, blocks of 7 days (pre-registered)."""
    if len(df) < 2:
        return (float("nan"), float("nan"))
    d = df.assign(day=pd.to_datetime(df["t"]).dt.floor("D")).sort_values("t")
    days = d["day"].drop_duplicates().to_list()
    by_day = {k: g[col].to_numpy() for k, g in d.groupby("day")}
    L = 7
    starts = list(range(max(1, len(days) - L + 1)))
    k = int(np.ceil(len(days) / L))
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(n_boot):
        vals = []
        for s in rng.choice(starts, size=k, replace=True):
            for dd in days[s:s + L]:
                vals.append(by_day[dd])
        v = np.concatenate(vals) if vals else np.array([np.nan])
        means.append(float(np.mean(v)))
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0}
    lo, hi = boot_ci(df, "edge")
    return {"n": int(len(df)), "success_rate": round(float(df["success"].mean()), 3),
            "mean_edge_pct": round(float(df["edge"].mean()), 3), "ci95": [round(lo, 3), round(hi, 3)]}


def verdict(dev: dict, hold: dict) -> str:
    if dev.get("n", 0) < 30 or hold.get("n", 0) < 30:
        return "UNCLEAR"
    ok = lambda s: s["mean_edge_pct"] > 0 and s["success_rate"] >= 0.5 and s["ci95"][0] > 0  # noqa: E731
    bad = lambda s: s["ci95"][1] < 0  # noqa: E731
    if ok(dev) and ok(hold):
        return "USEFUL"
    if bad(dev) and bad(hold):
        return "HARMFUL"
    return "UNCLEAR"


def report(rows: list) -> dict:
    df = pd.DataFrame(rows)
    df["period"] = np.where(pd.to_datetime(df["t"]) < SPLIT, "dev", "holdout")
    out = {"version": "idea-replay-0.1", "rule": I.VERSION, "samples": int(len(df)),
           "from": df["t"].min(), "to": df["t"].max(), "by_kind": {}, "by_asset_kind": {}}
    for k, g in df.groupby("kind"):
        dev, ho = summary(g[g.period == "dev"]), summary(g[g.period == "holdout"])
        out["by_kind"][k] = {"dev": dev, "holdout": ho, "verdict": verdict(dev, ho)}
    for (a, k), g in df.groupby(["asset", "kind"]):
        dev, ho = summary(g[g.period == "dev"]), summary(g[g.period == "holdout"])
        out["by_asset_kind"][f"{a}|{k}"] = {"dev": dev, "holdout": ho, "verdict": verdict(dev, ho)}
    if "shadow_edge" in df:
        f = df[df["shadow_edge"].notna()].copy()
        f["diff"] = f["idea_pct"] - f["shadow_idea_pct"]
        res = {}
        for per in ("dev", "holdout"):
            g = f[f.period == per]
            lo, hi = boot_ci(g, "diff") if len(g) else (float("nan"), float("nan"))
            res[per] = {"n": int(len(g)), "shown_mean_edge_pct": round(float(g["edge"].mean()), 3) if len(g) else None,
                        "shadow_mean_edge_pct": round(float(g["shadow_edge"].mean()), 3) if len(g) else None,
                        "filter_better_share": round(float((g["diff"] > 0).mean()), 3) if len(g) else None,
                        "diff_ci95": [round(lo, 3), round(hi, 3)]}
        d, h = res["dev"], res["holdout"]
        v = "UNCLEAR"
        if d["n"] >= 30 and h["n"] >= 30:
            if d["diff_ci95"][0] > 0 and h["diff_ci95"][0] > 0:
                v = "HELPS"
            elif d["diff_ci95"][1] < 0 and h["diff_ci95"][1] < 0:
                v = "HURTS"
        out["btc_filter"] = dict(res, verdict=v)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default="XAU,BTC,ETH,SOL")
    ap.add_argument("--out", default=str(ROOT / "research" / "idea_replay"))
    a = ap.parse_args()
    run(a.assets.split(","), Path(a.out))
