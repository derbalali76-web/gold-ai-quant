#!/usr/bin/env python3
"""trail-0.1 (PREREG_TRAIL.md): E0 sell at the target vs E1 let a strong rise run with a floor at the target."""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import replay as R  # noqa: E402
from goldquant.trend import market_trend  # noqa: E402

SPLIT = pd.Timestamp("2026-06-01T00:00:00Z")


def trend_fn(P):
    F, C = P["feats"], P["close"]
    cache = {}

    def tr(t: pd.Timestamp) -> str:
        if t in cache:
            return cache[t]
        rows = {}
        for tf in F:
            i = int(C[tf].searchsorted(t, side="right"))
            if i < 1:
                return "UNKNOWN"
            rows[tf] = F[tf].iloc[i - 1]
        cache[t] = market_trend(rows, "RANGE")["direction"]
        return cache[t]
    return tr


def run_asset(a: str, buys: pd.DataFrame) -> list:
    P = R.prep(a)
    tr = trend_fn(P)
    h1 = P["bars"]["H1"]
    hi, lo, cl, idx = (h1[k].to_numpy() for k in ("high", "low", "close")) + (h1.index,) if False else \
        (h1["high"].to_numpy(), h1["low"].to_numpy(), h1["close"].to_numpy(), h1.index)
    atr = P["feats"]["H1"]["atr"].to_numpy()
    end_dev = int(idx.searchsorted(SPLIT)) - 1
    out = []
    for t, p in zip(buys["t"], buys["price"]):
        ts = pd.Timestamp(t)
        i = int(idx.searchsorted(ts))
        last = end_dev if ts < SPLIT else len(cl) - 1
        tgt = p + 15.0 if a == "XAU" else p * 1.0065
        cost = 2.0 if a == "XAU" else p * 0.0015
        w = np.where(hi[i:last + 1] >= tgt)[0]
        per = "dev" if ts < SPLIT else "holdout"
        if not len(w):
            v = (cl[last] - p - cost) / p * 100
            out.append({"asset": a, "period": per, "e0": v, "e1": v, "closed": False, "extra_h": 0, "above": False})
            continue
        k = i + int(w[0])
        e0 = (tgt - p - cost) / p * 100
        if tr(idx[k]) != "UP":
            out.append({"asset": a, "period": per, "e0": e0, "e1": e0, "closed": True, "extra_h": 0, "above": False})
            continue
        floor, peak, sold, j = tgt, max(tgt, cl[k]), None, k
        # the bar that touched the target: keep; from its close on, trail
        floor = max(floor, peak - atr[k])
        for j in range(k + 1, last + 1):
            if lo[j] <= floor:
                sold = min(floor, h1["open"].iat[j]) if h1["open"].iat[j] < floor else floor
                break
            peak = max(peak, cl[j])
            floor = max(floor, peak - atr[j])
            if tr(idx[j] + pd.Timedelta(hours=1)) != "UP":
                sold = cl[j]
                break
        if sold is None:
            e1 = (cl[last] - p - cost) / p * 100
            out.append({"asset": a, "period": per, "e0": e0, "e1": e1, "closed": False, "extra_h": j - k, "above": cl[last] > tgt})
        else:
            e1 = (sold - p - cost) / p * 100
            out.append({"asset": a, "period": per, "e0": e0, "e1": e1, "closed": True, "extra_h": j - k, "above": sold > tgt})
    return out


def main():
    rows = pd.DataFrame([json.loads(x) for x in gzip.open(HERE / "samples.jsonl.gz", "rt")])
    buys = rows[(rows.kind == "BUY_NOW") & (rows["mode"] == "cash")].sort_values("t")
    res = []
    for a in ("XAU", "BTC", "ETH", "SOL"):
        res += run_asset(a, buys[buys.asset == a])
    df = pd.DataFrame(res)
    rep = {"version": "trail-0.1"}
    for per in ("dev", "holdout"):
        g = df[df.period == per]
        held = g[g.extra_h > 0]
        rep[per] = {"buys": int(len(g)), "e0_mean_net_pct": round(float(g.e0.mean()), 3), "e1_mean_net_pct": round(float(g.e1.mean()), 3),
                    "e0_closed_mean": round(float(g[g.closed].e0.mean()), 3), "e1_closed_mean": round(float(g[g.closed].e1.mean()), 3),
                    "kept_share": round(float((g.extra_h > 0).mean()), 3),
                    "median_extra_hours_when_kept": float(held.extra_h.median()) if len(held) else None,
                    "sold_above_target_share": round(float(g.above.mean()), 3),
                    "by_asset": {a: {"e0": round(float(x.e0.mean()), 3), "e1": round(float(x.e1.mean()), 3), "n": int(len(x))}
                                 for a, x in g.groupby("asset")}}
    rep["verdict_E1_better"] = all(rep[p]["e1_mean_net_pct"] > rep[p]["e0_mean_net_pct"] for p in ("dev", "holdout"))
    (HERE / "trail_report.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
