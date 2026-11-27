#!/usr/bin/env python3
"""spot-hold-0.1 (see PREREG_SPOT.md): the owner's spot method on the replayed «اشترِ الآن» moments."""
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

SPLIT = pd.Timestamp("2026-06-01T00:00:00Z")
COST_PCT = 0.0015
GOLD_COST, GOLD_TP, TP = 2.0, 15.0, 0.0065
STUCK_H = 30 * 24


def daily_ema50(asset: str) -> pd.Series:
    if asset == "XAU":
        h1 = R.load("XAU")["H1"]
        d = h1["close"].resample("1D").last().dropna()
    else:
        d = R.CS.load_bars(R.ROOT / "market_data", R.SYM[asset], "1d")["close"]
    e = d.ewm(span=50, adjust=False).mean()
    e.index = e.index + pd.Timedelta(days=1)  # known once the daily bar has closed
    return e


def simulate(asset: str, buys: pd.DataFrame, h1: pd.DataFrame, ema: pd.Series, f1: bool, cap: int | None) -> list:
    hi, cl, idx = h1["high"].to_numpy(), h1["close"].to_numpy(), h1.index
    end_dev = int(idx.searchsorted(SPLIT)) - 1          # last H1 bar opening before the split
    out, open_until = [], []
    reset = False
    for t, p in zip(buys["t"], buys["price"]):
        ts = pd.Timestamp(t)
        if ts >= SPLIT and not reset:  # periods are separate: dev buys do not occupy holdout slots
            open_until, reset = [], True
        if f1:
            e = ema[ema.index <= ts]
            if e.empty or p < float(e.iloc[-1]):
                continue
        open_until = [x for x in open_until if x > ts]
        if cap is not None and len(open_until) >= cap:
            continue
        i = int(idx.searchsorted(ts))
        last = end_dev if ts < SPLIT else len(cl) - 1
        target = p + GOLD_TP if asset == "XAU" else p * (1 + TP)
        cost = GOLD_COST if asset == "XAU" else p * COST_PCT
        w = np.where(hi[i:last + 1] >= target)[0]
        if len(w):
            k = i + int(w[0])
            close_t = idx[k] + pd.Timedelta(hours=1)
            net = (target - p - cost) / p * 100
            hours = (close_t - ts).total_seconds() / 3600
            closed = True
        else:
            close_t = pd.Timestamp.max.tz_localize("UTC")
            net = (cl[last] - p - cost) / p * 100
            hours = (idx[last] + pd.Timedelta(hours=1) - ts).total_seconds() / 3600
            closed = False
        open_until.append(close_t)
        out.append({"asset": asset, "t": t, "period": "dev" if ts < SPLIT else "holdout", "closed": closed,
                    "hours": hours, "net": net, "stuck": (not closed) and hours > STUCK_H})
    return out


def summ(g: pd.DataFrame) -> dict:
    if g.empty:
        return {"buys": 0}
    c = g[g.closed]
    return {"buys": int(len(g)), "closed_share": round(float(g.closed.mean()), 3),
            "median_hours_to_close": round(float(c.hours.median()), 1) if len(c) else None,
            "mean_net_pct": round(float(g.net.mean()), 3), "stuck_share": round(float(g.stuck.mean()), 3),
            "worst_open_pct": round(float(g[~g.closed].net.min()), 1) if (~g.closed).any() else None,
            "total_net_pct": round(float(g.net.sum()), 1)}


def main() -> None:
    rows = pd.DataFrame([json.loads(x) for x in gzip.open(HERE / "samples.jsonl.gz", "rt")])
    buys_all = rows[(rows.kind == "BUY_NOW") & (rows["mode"] == "cash")].sort_values("t")
    variants = {"S0": (False, None), "F1": (True, None), "C3": (False, 3), "F1+C3": (True, 3)}
    res = {v: [] for v in variants}
    for a in ("XAU", "BTC", "ETH", "SOL"):
        h1 = R.load(a)["H1"]
        ema = daily_ema50(a)
        b = buys_all[buys_all.asset == a]
        for v, (f1, cap) in variants.items():
            res[v] += simulate(a, b, h1, ema, f1, cap)
    rep = {"version": "spot-hold-0.1", "variants": {}}
    for v, rr in res.items():
        df = pd.DataFrame(rr)
        rep["variants"][v] = {per: {"all": summ(df[df.period == per]),
                                    **{a: summ(df[(df.period == per) & (df.asset == a)]) for a in ("XAU", "BTC", "ETH", "SOL")}}
                              for per in ("dev", "holdout")}
    s0 = rep["variants"]["S0"]
    for v in variants:
        x = rep["variants"][v]
        ok = all(x[p]["all"].get("buys", 0) > 0 for p in ("dev", "holdout"))  # no buys in a period = no verdict
        better = ok and v != "S0" and all(x[p]["all"]["mean_net_pct"] > s0[p]["all"]["mean_net_pct"] and
                                          x[p]["all"]["stuck_share"] <= s0[p]["all"]["stuck_share"] for p in ("dev", "holdout"))
        profitable = ok and all(x[p]["all"]["mean_net_pct"] > 0 for p in ("dev", "holdout"))
        x["verdict"] = {"better_than_S0": better, "profitable": profitable}
    (HERE / "spot_report.json").write_text(json.dumps(rep, indent=1) + "\n")
    for v, x in rep["variants"].items():
        print(v, x["verdict"])
        for p in ("dev", "holdout"):
            print("  ", p, x[p]["all"])
            for a in ("XAU", "BTC", "ETH", "SOL"):
                print("      ", a, x[p][a])


if __name__ == "__main__":
    main()
