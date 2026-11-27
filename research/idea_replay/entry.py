#!/usr/bin/env python3
"""entry-0.1 (PREREG_ENTRY.md): S0 vs limit −0.4 % (L04), split entry (D2), buyer pressure (TB)."""
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
STUCK_H = 30 * 24


def target_of(a, cost_basis):
    return cost_basis + 15.0 if a == "XAU" else cost_basis * 1.0065


def cost_of(a, cost_basis):
    return 2.0 if a == "XAU" else cost_basis * 0.0015      # per unit (ounce / dollar-equivalent) per round trip


def run(a: str, buys: pd.DataFrame) -> list:
    h1 = R.load(a)["H1"]
    hi, lo, cl, idx = h1["high"].to_numpy(), h1["low"].to_numpy(), h1["close"].to_numpy(), h1.index
    tb = None
    if a != "XAU":
        raw = R.CS.load_bars(R.ROOT / "market_data", R.SYM[a], "1h")
        ratio = (raw["taker_buy_volume"].rolling(4).sum() / raw["volume"].rolling(4).sum())
        ratio.index = ratio.index + pd.Timedelta(hours=1)          # known when the 4th bar closes
        tb = ratio
    end_dev = int(idx.searchsorted(SPLIT)) - 1
    out = []

    def hold(i, last, basis):
        """from bar i, sell at target over basis; returns (net % of basis incl. cost, closed, hours)."""
        tgt = target_of(a, basis)
        w = np.where(hi[i:last + 1] >= tgt)[0]
        if len(w):
            return (tgt - basis - cost_of(a, basis)) / basis * 100, True, int(w[0]) + 1
        return (cl[last] - basis - cost_of(a, basis)) / basis * 100, False, last - i + 1

    for t, p in zip(buys["t"], buys["price"]):
        ts = pd.Timestamp(t)
        i = int(idx.searchsorted(ts))
        last = end_dev if ts < SPLIT else len(cl) - 1
        per = "dev" if ts < SPLIT else "holdout"
        rec = {"asset": a, "period": per}
        # S0
        n, c, h = hold(i, last, p)
        rec["S0"] = (n, True, c, h)
        # L04: limit at p*0.996 within 24 h
        lim = p * 0.996
        f = np.where(lo[i:min(i + 24, last + 1)] <= lim)[0]
        if len(f):
            j = i + int(f[0])
            fill = min(lim, h1["open"].iat[j]) if h1["open"].iat[j] < lim else lim
            # the fill bar itself may also reach the target: count from the next bar to stay conservative
            n, c, h = hold(j + 1, last, fill)
            rec["L04"] = (n, True, c, h + (j - i))
        else:
            rec["L04"] = (0.0, False, True, 0)
        # D2: half at p, half limit p*0.99 valid 24 h, only if filled before the target over p is reached
        t0 = target_of(a, p)
        reach = np.where(hi[i:last + 1] >= t0)[0]
        reach_i = i + int(reach[0]) if len(reach) else None
        f2 = np.where(lo[i:min(i + 24, last + 1)] <= p * 0.99)[0]
        j2 = i + int(f2[0]) if len(f2) else None
        if j2 is not None and (reach_i is None or j2 < reach_i):
            basis = (p + p * 0.99) / 2
            n, c, h = hold(j2 + 1, last, basis)
            rec["D2"] = (n, True, c, h + (j2 - i))
            rec["D2_inv"] = (n, 1.0)
        else:
            # only the first half bought: same % as S0 on half the money -> per unit of money it is half
            n, c, h = rec["S0"][0], rec["S0"][2], rec["S0"][3]
            rec["D2"] = (n / 2, True, c, h)
            rec["D2_inv"] = (n / 2, 0.5)
        # TB
        if tb is None:
            rec["TB"] = rec["S0"]
        else:
            k = tb[tb.index <= ts]
            if not k.empty and float(k.iloc[-1]) >= 0.5:
                rec["TB"] = rec["S0"]
            else:
                rec["TB"] = (0.0, False, True, 0)
        out.append(rec)
    return out


def main():
    rows = pd.DataFrame([json.loads(x) for x in gzip.open(HERE / "samples.jsonl.gz", "rt")])
    buys = rows[(rows.kind == "BUY_NOW") & (rows["mode"] == "cash")].sort_values("t")
    recs = []
    for a in ("XAU", "BTC", "ETH", "SOL"):
        recs += run(a, buys[buys.asset == a])
    rep = {"version": "entry-0.1"}
    for v in ("S0", "L04", "D2", "TB"):
        rep[v] = {}
        for per in ("dev", "holdout"):
            for scope in ("all", "XAU", "BTC", "ETH", "SOL"):
                rr = [r for r in recs if r["period"] == per and (scope == "all" or r["asset"] == scope)]
                ent = [r[v] for r in rr if r[v][1]]
                rep[v][f"{per}|{scope}"] = {
                    "signals": len(rr), "entries": len(ent),
                    "mean_net_per_signal": round(float(np.mean([r[v][0] for r in rr])), 3) if rr else None,
                    "mean_net_per_entry": round(float(np.mean([e[0] for e in ent])), 3) if ent else None,
                    "stuck_share": round(float(np.mean([(not e[2]) and e[3] > STUCK_H for e in ent])), 3) if ent else None,
                    "total": round(float(sum(r[v][0] for r in rr)), 1)}
    for per in ("dev", "holdout"):  # D2 per dollar actually invested (reported after the first run; see notes)
        rr = [r for r in recs if r["period"] == per]
        rep["D2"][f"{per}|per_dollar_invested"] = round(sum(r["D2_inv"][0] for r in rr) / sum(r["D2_inv"][1] for r in rr), 3)
    s0 = rep["S0"]
    for v in ("L04", "D2", "TB"):
        x = rep[v]
        rep[v]["verdict_better"] = all(
            x[f"{p}|all"]["mean_net_per_signal"] > s0[f"{p}|all"]["mean_net_per_signal"] and
            x[f"{p}|all"]["stuck_share"] <= s0[f"{p}|all"]["stuck_share"] for p in ("dev", "holdout"))
    (HERE / "entry_report.json").write_text(json.dumps(rep, indent=1) + "\n")
    for v in ("S0", "L04", "D2", "TB"):
        print(v, rep[v].get("verdict_better", ""))
        for p in ("dev", "holdout"):
            print("  ", p, rep[v][f"{p}|all"])
            for a in ("XAU", "BTC", "ETH", "SOL"):
                print("      ", a, rep[v][f"{p}|{a}"]["mean_net_per_signal"], rep[v][f"{p}|{a}"]["entries"])


if __name__ == "__main__":
    main()
