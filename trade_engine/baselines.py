"""Phase 1: reference strategies on DEVELOPMENT data only (2021-01-01 .. 2025-11-14). The holdout stays sealed.

No rule of the pre-registered family is evaluated here; these numbers set the bar the rules must clear.
Run: python -m trade_engine.baselines  -> trade_engine/reports/phase1_baselines.json
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

from . import data
from .metrics import summary, max_dd, boot
from .rules import DEV_START, HOLDOUT_START, FOLDS, features, ENTRY_BARS, HOLD_BARS
from .sim import Costs, Market, Order, run

OUT = Path(__file__).resolve().parent / "reports"


def generic(row, market=False) -> Order | None:
    a, c = row["atr"], row["close"]
    if market:
        return Order(row["t"], target=c + 3 * a, stop=c - 2 * a, limit=None, entry_bars=ENTRY_BARS, hold_bars=HOLD_BARS)
    lim = c - 0.5 * a
    stop = lim - 2 * a
    return Order(row["t"], target=lim + 1.5 * (lim - stop), stop=stop, limit=lim, entry_bars=ENTRY_BARS, hold_bars=HOLD_BARS)


def buy_hold(h4: pd.DataFrame, start, end) -> dict:
    c = h4["close"][(h4.index + pd.Timedelta(hours=4) > start) & (h4.index + pd.Timedelta(hours=4) <= end)]
    r = c.pct_change().dropna().to_numpy()
    eq = np.cumprod(1 + r)
    per_year = {str(y): round(100 * (g.iloc[-1] / g.iloc[0] - 1), 1) for y, g in c.groupby(c.index.year)}
    return {"total_return_pct": round(100 * (c.iloc[-1] / c.iloc[0] - 1), 1),
            "max_drawdown_pct": round(100 * max_dd(r), 1), "by_year_pct": per_year,
            "mean_4h_pct": round(100 * r.mean(), 4), "note": "always invested; not comparable trade-by-trade"}


def per_fold(results) -> dict:
    out = {}
    for a, b in FOLDS:
        a, b = pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")
        sel = [r for r in results if a <= pd.Timestamp(r.t) < b]
        s = summary(sel)
        out[f"{a.date()}..{b.date()}"] = {k: s[k] for k in ("filled", "p_target_first", "mean_net_pct", "profit_factor")}
    return out


def main(argv) -> int:
    t0 = time.time()
    report = {"engine": "te-0.1.0-phase1", "window": [str(DEV_START), str(HOLDOUT_START)], "assets": {}}
    for sym in ("BTCUSDT", "SOLUSDT"):
        h1, q = data.load(sym, "1h"), data.load(sym, "15m")
        h4 = data.to_4h(h1)
        m = Market(q, h1)
        f = features(h4)
        dev = f[(f["t"] >= DEV_START) & (f["t"] < HOLDOUT_START - pd.Timedelta(days=7))]
        rep = {"data_sha": {"1h": data.fingerprint(sym, "1h"), "15m": data.fingerprint(sym, "15m")},
               "decision_bars": len(dev), "cash": {"total_return_pct": 0.0, "max_drawdown_pct": 0.0},
               "buy_hold": buy_hold(h4, DEV_START, HOLDOUT_START)}
        c = Costs.for_asset(sym)
        always = [generic(r) for _, r in dev.iterrows()]
        res = run(always, m, c)
        rep["always_limit"] = dict(summary(res), folds=per_fold(res),
                                   desc="every 4h close: limit close-0.5ATR, stop limit-2ATR, target 1.5R, 12h timeout, 5d max hold")
        rep["always_limit_cost_sensitivity"] = {str(s): {k: v for k, v in summary(run(always, m, Costs.for_asset(sym, s))).items()
                                                        if k in ("mean_net_pct", "profit_factor", "total_return_pct")}
                                                for s in (0.75, 2.0)}
        mk = [generic(r, market=True) for _, r in dev.iterrows()]
        rm = run(mk, m, c)
        rep["always_market"] = dict(summary(rm), folds=per_fold(rm), desc="every 4h close: market buy, stop -2ATR, target +3ATR, 5d")
        tr = dev[dev["close"] > dev["ema200"]]
        rt = run([generic(r) for _, r in tr.iterrows()], m, c)
        rep["trend_limit"] = dict(summary(rt), folds=per_fold(rt), desc="as always_limit, only when close > EMA200(4h)")
        # random entry: 100 seeds, 5 % of bars, same geometry -> the distribution a real rule must beat
        means, pfs, ns = [], [], []
        for seed in range(100):
            rng = np.random.default_rng(seed)
            pick = dev[rng.random(len(dev)) < 0.05]
            s = summary(run([generic(r) for _, r in pick.iterrows()], m, c))
            if s["mean_net_pct"] is not None:
                means.append(s["mean_net_pct"]); ns.append(s["filled"])
                if s["profit_factor"]:
                    pfs.append(s["profit_factor"])
        rep["random_limit"] = {"seeds": len(means), "filled_median": int(np.median(ns)),
                               "mean_net_pct_p5_p50_p95": [round(float(np.percentile(means, q)), 4) for q in (5, 50, 95)],
                               "profit_factor_p5_p50_p95": [round(float(np.percentile(pfs, q)), 3) for q in (5, 50, 95)],
                               "desc": "random 5 % of 4h closes, same geometry as always_limit, one position at a time"}
        report["assets"][sym] = rep
        print(sym, "done", round(time.time() - t0), "s", file=sys.stderr)
    OUT.mkdir(exist_ok=True)
    (OUT / "phase1_baselines.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
