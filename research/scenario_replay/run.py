#!/usr/bin/env python3
"""scenario-replay-0.1 runner — follows PREREG.md (commit 93c1ad4) exactly. Writes results.json."""
from __future__ import annotations

import glob
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "ledger"))
from goldquant import brief as BR  # noqa: E402
from goldquant.levels import compute_levels  # noqa: E402
from advice_units import score  # noqa: E402

CUT = pd.Timestamp("2025-11-15", tz="UTC")
SRC = {"XAU": ("market_data/bars/Dukascopy/XAUUSD/H1", "market_data/bars/Dukascopy/XAUUSD/M15"),
       "BTC": ("market_data/crypto/BTCUSDT/1h", "market_data/crypto/BTCUSDT/15m"),
       "ETH": ("market_data/crypto/ETHUSDT/1h", "market_data/crypto/ETHUSDT/15m"),
       "SOL": ("market_data/crypto/SOLUSDT/1h", "market_data/crypto/SOLUSDT/15m")}
COST = {"BTC": [0.32], "ETH": [0.32], "SOL": [0.44], "XAU": [0.10, 0.00, 0.30]}   # first = primary
WIN = {"crypto": 24, "gold": 23}
REPS, SEED = 10_000, 20261122
WINDOWS = [168, 24]                                                             # first = primary


def load(d):
    fs = sorted(glob.glob(str(ROOT / d / "*.csv.gz")))
    df = pd.concat(pd.read_csv(f) for f in fs)
    df.index = pd.to_datetime(df["open_time"], format="ISO8601", utc=True)
    df = df[["open", "high", "low", "close"]].astype(float).sort_index()
    return df[~df.index.duplicated()]


def boot_p(gains, months):
    by = {}
    for g, m in zip(gains, months):
        by.setdefault(m, []).append(g)
    obs = sum(gains) / len(gains)
    blocks = [[x - obs for x in b] for b in by.values()]
    rnd, hit = random.Random(SEED), 0
    for _ in range(REPS):
        s = n = 0
        for _ in range(len(blocks)):
            b = blocks[rnd.randrange(len(blocks))]
            s += sum(b); n += len(b)
        hit += (n and s / n >= obs)
    return (hit + 1) / (REPS + 1)


def likely_down(table, p0, s1, r1, atr):
    """brief.attach_outcome3 logic, returning DOWN / UP / NONE / None (no usable cell or no lead)."""
    class B:  # minimal stand-in for the brief object
        outcome3 = None
    b = B()
    BR.attach_outcome3(b, table, p0, s1, r1, atr)
    return None if b.outcome3 is None else b.outcome3.likely


def events(asset):
    h1d, m15d = SRC[asset]
    h1, m15 = load(h1d), load(m15d)
    h1, m15 = h1[h1.index < CUT], m15[m15.index < CUT]
    h4 = h1.resample("4h", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    win = WIN["gold" if asset == "XAU" else "crypto"]
    start = max(h1.index[0] + pd.Timedelta(days=730), m15.index[0] + pd.Timedelta(days=10))
    start = start.normalize() + pd.Timedelta(days=1)
    rows = h1.reset_index().values.tolist()          # [ts, o, h, l, c]
    tindex = h1.index
    tables, out, all_days = {}, [], 0
    day = start
    while day + pd.Timedelta(hours=168) <= CUT:
        mkey = day.strftime("%Y-%m")
        if mkey not in tables:                        # walk-forward: built from the 2 years before the month starts
            m0 = day.replace(day=1)
            hist = h1[(h1.index >= m0 - pd.Timedelta(days=730)) & (h1.index + pd.Timedelta(hours=1) <= m0)]
            tables[mkey] = {"outcome3": BR.outcome_table(hist, win)}
        i = int(tindex.searchsorted(day))
        if i >= len(rows) or rows[i][0] - day >= pd.Timedelta(hours=1):
            day += pd.Timedelta(days=1); continue
        p0 = float(rows[i][1])
        bars = {"M15": m15[(m15.index >= day - pd.Timedelta(days=12)) & (m15.index < day)],
                "H1": h1[(h1.index >= day - pd.Timedelta(days=70)) & (h1.index < day)],
                "H4": h4[(h4.index >= day - pd.Timedelta(days=210)) & (h4.index < day)]}
        if bars["M15"].empty or len(bars["H1"]) < 200:
            day += pd.Timedelta(days=1); continue
        lv = compute_levels(bars, day, p0)
        sup = sorted([x["price"] for x in lv["supports"] if x["price"] < p0], reverse=True)
        res = sorted([x["price"] for x in lv["resistances"] if x["price"] > p0])
        if not sup or not res:
            day += pd.Timedelta(days=1); continue
        s1, r1 = sup[0], res[0]
        s2 = sup[1] if len(sup) > 1 else None
        lk = likely_down(tables[mkey], p0, s1, r1, lv["atr_h1"])
        wins = {}
        for W in WINDOWS:
            j, w = i, []
            while j < len(rows) and rows[j][0] < day + pd.Timedelta(hours=W):
                r = rows[j]; w.append([r[0].isoformat(), r[1], r[2], r[3], r[4]]); j += 1
            wins[W] = w
        # calibration: was S1 reached before R1 within the table's window?
        first = None
        for r in wins[168][:win]:
            dn, upx = r[3] <= s1, r[2] >= r1
            if dn and upx:
                first = "BOTH"; break
            if dn:
                first = "DOWN"; break
            if upx:
                first = "UP"; break
        all_days += 1
        out.append({"date": day, "p0": p0, "s1": s1, "s2": s2, "r1": r1, "likely": lk, "first": first or "NONE", "win": wins})
        day += pd.Timedelta(days=1)
    return out, all_days, start


def rec(e, at, cost_pct):
    return {"hold": {"advice": "SELL_NOW", "at": at, "exit": e["r1"]}, "hours": {"down": [e["s1"]]},
            "price_at_record": e["p0"], "cost": e["p0"] * cost_pct / 100}


def summarise(res, uncond, dates):
    n = len(res)
    g = [r["pre_emptive"]["gain_pct"] for r in res]
    ab = [r["after_break"]["gain_pct"] for r in res]
    order = sorted(range(n), key=lambda i: dates[i])
    h1, h2 = order[: n // 2], order[n // 2:]
    yrs = {}
    for i in range(n):
        yrs.setdefault(dates[i].year, []).append(g[i])
    m = sum(g) / n
    return {"n": n, "mean_gain_pct": round(m, 4), "median_gain_pct": round(sorted(g)[n // 2], 4),
            "beat_hold_rate": round(sum(x > 0 for x in g) / n, 4), "after_break_mean_pct": round(sum(ab) / n, 4),
            "uncond_n": len(uncond), "uncond_mean_pct": round(sum(uncond) / len(uncond), 4) if uncond else None,
            "half1_mean": round(sum(g[i] for i in h1) / max(len(h1), 1), 4),
            "half2_mean": round(sum(g[i] for i in h2) / max(len(h2), 1), 4),
            "by_year": {y: {"n": len(v), "mean": round(sum(v) / len(v), 4)} for y, v in sorted(yrs.items())},
            "no_rebuy": sum(r["pre_emptive"]["how"] == "NO_REBUY" for r in res),
            "protection": sum(r["pre_emptive"]["how"] == "PROTECTION" for r in res),
            "bought_back": sum(r["pre_emptive"]["how"] == "BOUGHT_BACK" for r in res),
            "rose_no_return": sum(r["pre_emptive"]["rose_no_return"] for r in res),
            "partial_30_mean_pct": round(0.3 * m, 4), "partial_50_mean_pct": round(0.5 * m, 4),
            "worst_pct": round(min(g), 4), "best_pct": round(max(g), 4)}


def main():
    out = {"study": "scenario-replay-0.1", "prereg_commit": "93c1ad4",
           "prereg_sha256": "7649a33c7010860ba6e2615d25b1e67c72a02f93ff9805e470367ffa4d8b2332",
           "cut": CUT.isoformat(), "assets": {}}
    for asset in ("XAU", "BTC", "ETH", "SOL"):
        ev, days, start = events(asset)
        sig = [e for e in ev if e["likely"] == "DOWN"]
        cal = {k: sum(e["first"] == k for e in sig) for k in ("DOWN", "UP", "BOTH", "NONE")}
        A = {"start": start.date().isoformat(), "days_with_levels": days, "likely_counts":
             {k: sum(e["likely"] == k for e in ev) for k in ("DOWN", "UP", "NONE", None)},
             "calibration_when_down_24h": cal, "variants": {}}
        A["likely_counts"] = {str(k): v for k, v in A["likely_counts"].items()}
        for W in WINDOWS:
            for ci, cost in enumerate(COST[asset]):
                for pol in ("P1", "P2"):
                    lvl = (lambda e: e["s2"] if e["s2"] is not None else e["s1"]) if pol == "P1" else (lambda e: e["s1"])
                    key = f"{pol}_w{W}_cost{cost}"
                    if not sig:
                        A["variants"][key] = {"n": 0, "class": "TOO_FEW"}; continue
                    res = [score(rec(e, lvl(e), cost), e["win"][W]) for e in sig]
                    unc = [score(rec(e, lvl(e), cost), e["win"][W])["pre_emptive"]["gain_pct"] for e in ev]
                    dates = [e["date"] for e in sig]
                    s = summarise(res, unc, dates)
                    s["primary"] = (ci == 0 and W == WINDOWS[0])
                    if s["n"] >= 30:
                        s["p_boot"] = round(boot_p([r["pre_emptive"]["gain_pct"] for r in res], [d.strftime("%Y-%m") for d in dates]), 5)
                    A["variants"][key] = s
        prim = sorted([(k, v) for k, v in A["variants"].items() if v.get("primary") and "p_boot" in v], key=lambda kv: kv[1]["p_boot"])
        run = 0.0
        for idx, (k, v) in enumerate(prim):
            run = max(run, min(1.0, (len(prim) - idx) * v["p_boot"])); v["p_holm"] = round(run, 5)
        for k, v in A["variants"].items():
            if not v.get("primary"):
                v.setdefault("class", "REPORT_ONLY"); continue
            if v.get("n", 0) < 30:
                v["class"] = "TOO_FEW"; continue
            ok = (v["mean_gain_pct"] > 0 and v["p_holm"] < 0.05 and v["beat_hold_rate"] >= 0.5
                  and v["mean_gain_pct"] > v["after_break_mean_pct"] and v["mean_gain_pct"] > (v["uncond_mean_pct"] or 0)
                  and v["half1_mean"] > 0 and v["half2_mean"] > 0)
            v["class"] = "EXPLORATORY_PROMISING" if ok else "NOT_SUPPORTED"
        out["assets"][asset] = A
        print(asset, "days", days, "DOWN events", len(sig), flush=True)
    Path(__file__).with_name("results.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    print("written")


if __name__ == "__main__":
    main()
