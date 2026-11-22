#!/usr/bin/env python3
"""explore-sell-rebuy-0.1 runner — follows PREREG.md (commit 6d2a738) exactly. Writes results.json."""
from __future__ import annotations

import glob
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ledger"))
from advice_units import score  # noqa: E402

CUT = datetime(2025, 11, 15, tzinfo=timezone.utc)
SRC = {"XAU": "market_data/bars/Dukascopy/XAUUSD/H1", "BTC": "market_data/crypto/BTCUSDT/1h",
       "ETH": "market_data/crypto/ETHUSDT/1h", "SOL": "market_data/crypto/SOLUSDT/1h"}
COST = {"BTC": [0.32], "ETH": [0.32], "SOL": [0.44], "XAU": [0.10, 0.00, 0.30]}   # first = primary
GRID = [(k, p) for k in (0.5, 1.0) for p in (0.5, 1.0)]
REPS, SEED = 10_000, 20261122


def load(asset):
    fs = sorted(glob.glob(str(ROOT / SRC[asset] / "*.csv.gz")))
    df = pd.concat([pd.read_csv(f) for f in fs])
    df["t"] = pd.to_datetime(df["open_time"], format="ISO8601", utc=True)
    df = df[df["t"] < CUT].drop_duplicates("t").sort_values("t").reset_index(drop=True)
    return df[["t", "open", "high", "low", "close"]]


def events(df):
    t = df["t"]
    day = t.dt.floor("D")
    d = df.groupby(day).agg(h=("high", "max"), l=("low", "min"), c=("close", "last"))
    pc = d["c"].shift(1)
    tr = pd.concat([d["h"] - d["l"], (d["h"] - pc).abs(), (d["l"] - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().shift(1)          # day D uses days before D only
    rows = df.values.tolist()
    ts = [x.to_pydatetime() for x in t]
    first = {}
    for i, x in enumerate(ts):
        first.setdefault(x.replace(hour=0, minute=0, second=0, microsecond=0), i)
    out = []
    for D, i in first.items():
        if i < 72 or ts[i] - D >= timedelta(hours=1):
            continue
        if D + timedelta(hours=168) > CUT:
            continue
        a = atr.get(pd.Timestamp(D))
        if a is None or pd.isna(a) or a <= 0:
            continue
        prior = rows[i - 72:i]
        S = min(r[3] for r in prior)
        p0 = rows[i][1]
        # 24 h return to t from closed bars: last close vs close 24 bars earlier
        r24 = rows[i - 1][4] / rows[i - 25][4] - 1 if i >= 25 else None
        j = i
        win = []
        while j < len(rows) and ts[j] < D + timedelta(hours=168):
            r = rows[j]
            win.append([ts[j].isoformat(), r[1], r[2], r[3], r[4]])
            j += 1
        if len(win) < 24:
            continue
        out.append({"date": D, "p0": p0, "S": S, "atr": float(a), "r24": r24, "win": win})
    return out


def rec_for(e, k, cost_pct):
    return {"hold": {"advice": "SELL_NOW", "at": e["S"] - k * e["atr"], "exit": e["p0"] + e["atr"]},
            "hours": {"down": [e["S"]]}, "price_at_record": e["p0"], "cost": e["p0"] * cost_pct / 100}


def boot_p(gains, months):
    by = {}
    for g, m in zip(gains, months):
        by.setdefault(m, []).append(g)
    blocks = list(by.values())
    obs = sum(gains) / len(gains)
    rnd = random.Random(SEED)
    centered = [[x - obs for x in b] for b in blocks]
    hit = 0
    for _ in range(REPS):
        s = n = 0
        for _ in range(len(blocks)):
            b = centered[rnd.randrange(len(blocks))]
            s += sum(b)
            n += len(b)
        if n and s / n >= obs:
            hit += 1
    return (hit + 1) / (REPS + 1)


def summarise(res, dates):
    n = len(res)
    g = [r["pre_emptive"]["gain_pct"] for r in res]
    ab = [r["after_break"]["gain_pct"] for r in res]
    mean = sum(g) / n
    order = sorted(range(n), key=lambda i: dates[i])
    h1, h2 = order[: n // 2], order[n // 2:]
    yrs = {}
    for i in range(n):
        yrs.setdefault(dates[i].year, []).append(g[i])
    return {"n": n, "mean_gain_pct": round(mean, 4), "median_gain_pct": round(sorted(g)[n // 2], 4),
            "beat_hold_rate": round(sum(x > 0 for x in g) / n, 4),
            "after_break_mean_pct": round(sum(ab) / n, 4),
            "half1_mean": round(sum(g[i] for i in h1) / max(len(h1), 1), 4),
            "half2_mean": round(sum(g[i] for i in h2) / max(len(h2), 1), 4),
            "by_year": {y: {"n": len(v), "mean": round(sum(v) / len(v), 4)} for y, v in sorted(yrs.items())},
            "no_rebuy": sum(r["pre_emptive"]["how"] == "NO_REBUY" for r in res),
            "protection": sum(r["pre_emptive"]["how"] == "PROTECTION" for r in res),
            "bought_back": sum(r["pre_emptive"]["how"] == "BOUGHT_BACK" for r in res),
            "rose_no_return": sum(r["pre_emptive"]["rose_no_return"] for r in res),
            "worst_pct": round(min(g), 4), "best_pct": round(max(g), 4)}


def main():
    out = {"study": "explore-sell-rebuy-0.1", "prereg_commit": "6d2a738",
           "prereg_sha256": "18fb579dc0e2dd30f28d836c0944cf5b412b99f6778303db7df741ec4249acf2",
           "cut": CUT.isoformat(), "assets": {}}
    for asset in ("XAU", "BTC", "ETH", "SOL"):
        ev = events(load(asset))
        A = {"days": len(ev), "first": ev[0]["date"].date().isoformat(), "last": ev[-1]["date"].date().isoformat(),
             "variants": {}}
        for ci, cost in enumerate(COST[asset]):
            for k, prox in GRID:
                sel = [e for e in ev if e["r24"] is not None and e["r24"] < 0 and e["S"] < e["p0"] <= e["S"] + prox * e["atr"]]
                key = f"k{k}_prox{prox}_cost{cost}"
                if not sel:
                    A["variants"][key] = {"n": 0, "class": "TOO_FEW"}
                    continue
                res = [score(rec_for(e, k, cost), e["win"]) for e in sel]
                dates = [e["date"] for e in sel]
                s = summarise(res, dates)
                uncond = [score(rec_for(e, k, cost), e["win"])["pre_emptive"]["gain_pct"] for e in ev if e["S"] < e["p0"]]
                s["uncond_n"] = len(uncond)
                s["uncond_mean_pct"] = round(sum(uncond) / len(uncond), 4)
                s["primary_cost"] = ci == 0
                if s["n"] >= 30:
                    s["p_boot"] = round(boot_p([r["pre_emptive"]["gain_pct"] for r in res], [d.strftime("%Y-%m") for d in dates]), 5)
                A["variants"][key] = s
        # Holm across the 4 variants at primary cost
        prim = [(key, v) for key, v in A["variants"].items() if v.get("primary_cost") and "p_boot" in v]
        prim.sort(key=lambda kv: kv[1]["p_boot"])
        m = len(prim)
        running = 0.0
        for idx, (key, v) in enumerate(prim):
            running = max(running, min(1.0, (m - idx) * v["p_boot"]))
            v["p_holm"] = round(running, 5)
        for key, v in A["variants"].items():
            if not v.get("primary_cost"):
                v["class"] = "SENSITIVITY_ONLY"
                continue
            if v.get("n", 0) < 30:
                v["class"] = "TOO_FEW"
                continue
            ok = (v["mean_gain_pct"] > 0 and v["p_holm"] < 0.05 and v["beat_hold_rate"] >= 0.5
                  and v["mean_gain_pct"] > v["after_break_mean_pct"] and v["mean_gain_pct"] > v["uncond_mean_pct"]
                  and v["half1_mean"] > 0 and v["half2_mean"] > 0)
            v["class"] = "EXPLORATORY_PROMISING" if ok else "NOT_SUPPORTED"
        out["assets"][asset] = A
        print(asset, len(ev), "days", flush=True)
    p = Path(__file__).with_name("results.json")
    p.write_text(json.dumps(out, indent=1, default=str) + "\n")
    print("written", p)


if __name__ == "__main__":
    main()
