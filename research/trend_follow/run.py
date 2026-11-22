#!/usr/bin/env python3
"""trend-follow-0.1 runner — follows PREREG.md (commit 68c8c61) exactly. Writes results.json."""
from __future__ import annotations

import glob
import json
import math
import random
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CUT = pd.Timestamp("2025-11-15", tz="UTC")
COST = {"BTC": [0.16], "ETH": [0.16], "SOL": [0.22], "XAU": [0.05, 0.0, 0.15]}   # % per switch side, first = primary
REPS, SEED = 10_000, 20261122


def load(d):
    fs = sorted(glob.glob(str(ROOT / d / "*.csv.gz")))
    df = pd.concat(pd.read_csv(f) for f in fs)
    df.index = pd.to_datetime(df["open_time"], format="ISO8601", utc=True)
    df = df[["open", "high", "low", "close"]].astype(float).sort_index()
    return df[~df.index.duplicated()]


def daily(asset):
    if asset == "XAU":
        h = load("market_data/bars/Dukascopy/XAUUSD/H1")
        h = h[h.index >= pd.Timestamp("2016-01-01", tz="UTC")]
        g = h.groupby(h.index.floor("D"))
        d = pd.DataFrame({"open": g["open"].first(), "close": g["close"].last(), "n": g["close"].size()})
        d = d[d["n"] >= 6][["open", "close"]]
    else:
        start = {"BTC": "2018-01-01", "ETH": "2018-01-01", "SOL": "2020-09-01"}[asset]
        d = load(f"market_data/crypto/{asset}USDT/1d")[["open", "close"]]
        d = d[d.index >= pd.Timestamp(start, tz="UTC")]
    return d[d.index + pd.Timedelta(days=1) <= CUT]


def signal(closes: pd.Series, v: str, crypto: bool) -> bool | None:
    if v == "V3":
        if len(closes) < 200:
            return None
        return closes.iloc[-50:].mean() > closes.iloc[-200:].mean()
    look = {"V1": 365 if crypto else 252, "V2": 182 if crypto else 126}[v]
    if len(closes) <= look:
        return None
    return closes.iloc[-1] / closes.iloc[-1 - look] - 1 > 0


def simulate(d: pd.DataFrame, v: str, crypto: bool, cost_pct: float, cash_user: bool = False):
    c = cost_pct / 100
    idx = d.index
    mondays = [t for t in idx if t.weekday() == 0] if crypto else None
    if not crypto:   # gold: first trading day of each ISO week (Monday, or later if Monday is missing)
        seen, mondays = set(), []
        for t in idx:
            k = t.isocalendar()[:2]
            if k not in seen:
                seen.add(k); mondays.append(t)
    holding, units, cash, started = (not cash_user), 1.0, 0.0, False
    if cash_user:
        units, cash = 0.0, None   # cash user: measured as asset units bought back; starts with the value of 1 unit
    switches, days_in, days_tot = 0, 0, 0
    ue = {}                      # month-end units-equivalent (holder) or relative-to-buy-now (cash user)
    first_open = None
    ms = set(mondays)
    for t in idx:
        o, cl = d.at[t, "open"], d.at[t, "close"]
        if t in ms:
            s = signal(d.loc[d.index < t, "close"], v, crypto)
            if s is not None:
                if not started:
                    started, first_open = True, o
                    if cash_user:
                        cash = o          # value of 1 unit at the start
                if s and not holding:
                    units, cash, holding = cash / o * (1 - c), 0.0, True; switches += 1
                elif (not s) and holding and started:
                    cash, units, holding = units * o * (1 - c), 0.0, False; switches += 1
        if not started:
            continue
        days_tot += 1; days_in += holding
        eq_units = units if holding else cash / cl
        ue[t.strftime("%Y-%m")] = eq_units
    months = sorted(ue)
    logs = [math.log(ue[m]) for m in months]
    monthly = [logs[0]] + [logs[i] - logs[i - 1] for i in range(1, len(logs))]
    peak, mdd = -1e9, 0.0
    for x in logs:
        peak = max(peak, x); mdd = min(mdd, x - peak)
    return {"months": months, "monthly": monthly, "final_units": ue[months[-1]], "switches": switches,
            "time_in_market": days_in / max(days_tot, 1), "max_drawdown_units_pct": round((math.exp(mdd) - 1) * 100, 2),
            "first": months[0]}


def boot_p(x, months):
    obs = sum(x) / len(x)
    blocks = [[v - obs] for v in x]          # one value per calendar month = one block
    rnd, hit = random.Random(SEED), 0
    for _ in range(REPS):
        s = sum(blocks[rnd.randrange(len(blocks))][0] for _ in range(len(blocks)))
        hit += s / len(blocks) >= obs
    return (hit + 1) / (REPS + 1)


def main():
    out = {"study": "trend-follow-0.1", "prereg_commit": "68c8c61",
           "prereg_sha256": "2ccdff7599c0d1f4082bf8df35a57158133f08da59a7afe9d60c86bc843b92b6", "cut": CUT.isoformat(), "assets": {}}
    for asset in ("XAU", "BTC", "ETH", "SOL"):
        d = daily(asset)
        crypto = asset != "XAU"
        A = {"variants": {}}
        for ci, cost in enumerate(COST[asset]):
            for v in ("V1", "V2", "V3"):
                r = simulate(d, v, crypto, cost)
                x = r["monthly"]
                n = len(x)
                yrs = {}
                for m, val in zip(r["months"], x):
                    yrs.setdefault(m[:4], 0.0); yrs[m[:4]] += val
                s = {"months": n, "first_month": r["first"], "mean_monthly_log_units": round(sum(x) / n, 5),
                     "final_units_multiple": round(r["final_units"], 4), "switches": r["switches"],
                     "time_in_market": round(r["time_in_market"], 3), "max_drawdown_units_pct": r["max_drawdown_units_pct"],
                     "half1_mean": round(sum(x[: n // 2]) / (n // 2), 5), "half2_mean": round(sum(x[n // 2:]) / (n - n // 2), 5),
                     "by_year_units_pct": {y: round((math.exp(val) - 1) * 100, 2) for y, val in yrs.items()},
                     "primary": ci == 0}
                if ci == 0:
                    s["p_boot"] = round(boot_p(x, r["months"]), 5)
                    cu = simulate(d, v, crypto, cost, cash_user=True)
                    s["cash_user_final_vs_buy_at_start"] = round(cu["final_units"], 4)
                A["variants"][f"{v}_cost{cost}"] = s
        prim = sorted([(k, s) for k, s in A["variants"].items() if s["primary"]], key=lambda kv: kv[1]["p_boot"])
        run = 0.0
        for i, (k, s) in enumerate(prim):
            run = max(run, min(1.0, (len(prim) - i) * s["p_boot"])); s["p_holm"] = round(run, 5)
        for k, s in A["variants"].items():
            if not s["primary"]:
                s["class"] = "SENSITIVITY_ONLY"; continue
            ok = (s["months"] >= 36 and s["mean_monthly_log_units"] > 0 and s["p_holm"] < 0.05 and s["half1_mean"] > 0
                  and s["half2_mean"] > 0 and s["final_units_multiple"] > 1)
            s["class"] = "EXPLORATORY_PROMISING" if ok else "NOT_SUPPORTED"
        out["assets"][asset] = A
        print(asset, "done", flush=True)
    Path(__file__).with_name("results.json").write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
