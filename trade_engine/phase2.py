"""Phase 2 of te-0.1.0: evaluate the 48 pre-registered hypotheses on DEVELOPMENT data only (PREREG.md + A1).

Holdout prices are removed before anything is built. Outputs (trade_engine/reports/):
  phase2_results.json — every configuration, every metric, every criterion (pass or fail)
  phase2_table.md     — the same as a table
  phase2_selection.json — the qualified configurations (if any), file hashes, data fingerprints
Run: python -m trade_engine.phase2
"""
from __future__ import annotations
import hashlib, json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import data, rules
from .metrics import summary, wilson, pf, month_block_boot, brier_skill, reliability
from .sim import Costs, Market, Order, run, simulate
from .baselines import generic

HERE = Path(__file__).resolve().parent
OUT = HERE / "reports"
EVAL_START = pd.Timestamp("2022-01-01", tz="UTC")
EVAL_END = rules.HOLDOUT_START - rules.EMBARGO           # 2025-11-08
WINDOWS = [(pd.Timestamp(a, tz="UTC"), min(pd.Timestamp(b, tz="UTC"), EVAL_END)) for a, b in rules.FOLDS]
DRAWS, SEED = 1000, 20261118


def load_dev(sym: str):
    """Bars with open time < holdout start only (A1-1)."""
    h1, q = data.load(sym, "1h"), data.load(sym, "15m")
    h1, q = h1[h1.index < rules.HOLDOUT_START], q[q.index < rules.HOLDOUT_START]
    m = Market(q, h1)
    assert m.end <= rules.HOLDOUT_START
    f = rules.features(data.to_4h(h1))
    return f, m, {"1h": data.fingerprint(sym, "1h"), "15m": data.fingerprint(sym, "15m")}


def inputs(row: pd.Series, od: Order) -> list[float]:
    return [row["atr"] / row["close"], row["rsi"], row["close"] / row["ema200"] - 1, (row["close"] - od.limit) / row["atr"]]


def block_stats(res, months) -> dict:
    s = summary(res)
    filled = [r for r in res if r.filled]
    net = np.array([r.net for r in filled])
    mo = np.array([m for r, m in zip(res, months) if r.filled])
    ci_m = month_block_boot(mo, net, np.mean)
    s["mean_net_ci_pct"] = ci_m and (round(100 * ci_m[0], 4), round(100 * ci_m[1], 4))
    s["profit_factor_ci"] = month_block_boot(mo, net, pf)
    return s


def window_of(t: pd.Timestamp):
    for i, (a, b) in enumerate(WINDOWS):
        if a <= t < b:
            return i
    return None


def prob_eval(rows: list[dict]) -> dict:
    """rows: dicts with t, x (inputs), filled, target_first, win — for every placed order since 2021."""
    out = {}
    for key, pop in (("p_fill", "all"), ("p_target_first", "filled"), ("p_net_win", "filled")):
        P, B, Y = [], [], []
        for i, (a, b) in enumerate(WINDOWS):
            base_rows = [r for r in rows if r["t"] < a - rules.EMBARGO and (pop == "all" or r["filled"])]
            test = [r for r in rows if a <= r["t"] < b and (pop == "all" or r["filled"])]
            if not test:
                continue
            ytr = np.array([r[key] for r in base_rows], float)
            yte = np.array([r[key] for r in test], float)
            base = float(ytr.mean()) if len(ytr) else 0.5
            if len(ytr) >= 30 and 0 < ytr.sum() < len(ytr):
                mdl = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000))
                mdl.fit(np.array([r["x"] for r in base_rows]), ytr)
                p = mdl.predict_proba(np.array([r["x"] for r in test]))[:, 1]
            else:
                p = np.full(len(test), base)
            P.append(p); B.append(np.full(len(test), base)); Y.append(yte)
        if P:
            p, bse, y = np.concatenate(P), np.concatenate(B), np.concatenate(Y)
            out[key] = {"n": int(len(y)), "observed": round(float(y.mean()), 4), "observed_ci": wilson(int(y.sum()), len(y)),
                        "brier": round(float(((p - y) ** 2).mean()), 4), "brier_base": round(float(((bse - y) ** 2).mean()), 4),
                        "brier_skill": brier_skill(p, bse, y), "reliability": reliability(p, y)}
        else:
            out[key] = {"n": 0, "brier_skill": None}
    return out


def random_baseline(f_eval: pd.DataFrame, triples: list, n_orders: int, m: Market, costs: Costs, rule_mean: float, seed: int):
    if n_orders < 10 or not triples:
        return {"p_value": 1.0, "note": "fewer than 10 rule orders"}
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(triples), len(f_eval))
    nets = np.full(len(f_eval), np.nan)
    for i, (row, k) in enumerate(zip(f_eval.itertuples(), pick)):
        d_e, d_s, d_t, to = triples[k]
        lim = row.close - d_e * row.atr
        od = Order(row.t, target=lim + d_t * row.atr, stop=lim - d_s * row.atr, limit=lim, entry_bars=to,
                   hold_bars=rules.HOLD_BARS)
        if not (0 < od.stop < lim < od.target):
            continue
        r = simulate(od, m, costs)
        if r.outcome != "NO_DATA":
            nets[i] = r.net if r.filled else np.inf  # inf marks a placed-but-unfilled order
    valid = np.where(~np.isnan(nets))[0]
    means = []
    for _ in range(DRAWS):
        s = nets[rng.choice(valid, size=min(n_orders, len(valid)), replace=False)]
        s = s[np.isfinite(s)]
        if len(s):
            means.append(float(s.mean()))
    means = np.array(means)
    p = (1 + int((means >= rule_mean).sum())) / (1 + len(means))
    return {"p_value": round(p, 5), "pool": int(len(valid)), "pool_fill_rate": round(float(np.isfinite(nets[valid]).mean()), 4),
            "random_mean_net_pct_p5_p50_p95": [round(100 * float(np.percentile(means, q)), 4) for q in (5, 50, 95)],
            "rule_minus_random_median_pct": round(100 * (rule_mean - float(np.median(means))), 4)}


def holm(ps: list[float]) -> list[float]:
    order = np.argsort(ps)
    adj, run_max, n = [0.0] * len(ps), 0.0, len(ps)
    for rank, i in enumerate(order):
        run_max = max(run_max, min(1.0, (n - rank) * ps[i]))
        adj[i] = round(run_max, 5)
    return adj


def evaluate(sym: str, f: pd.DataFrame, m: Market, cfg: dict, seed: int) -> dict:
    costs = Costs.for_asset(sym)
    ods = rules.orders(f, cfg, rules.DEV_START, EVAL_END)
    by_t = {o.t: o for o in ods}
    res = run(ods, m, costs)
    frow = f.set_index("t")
    rows = []
    for r in res:
        t = pd.Timestamp(r.t); od = by_t[t]
        rows.append({"t": t, "x": inputs(frow.loc[t], od), "filled": float(r.filled),
                     "target_first": float(r.outcome == "TARGET"), "win": float(r.filled and r.net > 0),
                     "p_fill": float(r.filled), "p_target_first": float(r.outcome == "TARGET"),
                     "p_net_win": float(r.filled and r.net > 0), "r": r})
    ev = [x for x in rows if EVAL_START <= x["t"] < EVAL_END]
    eres = [x["r"] for x in ev]
    months = [x["t"].strftime("%Y-%m") for x in ev]
    st = block_stats(eres, months)
    no_data = sum(r.outcome == "NO_DATA" for r in eres)
    per_window = []
    for i, (a, b) in enumerate(WINDOWS):
        wr = [x["r"] for x in ev if a <= x["t"] < b]
        s = summary(wr)
        per_window.append({"window": f"{a.date()}..{b.date()}", "orders": s["orders"], "filled": s["filled"],
                           "p_target_first": s["p_target_first"], "mean_net_pct": s["mean_net_pct"], "profit_factor": s["profit_factor"]})
    sens = {}
    for k in (0.75, 2.0):
        sr = [r for r in run(ods, m, Costs.for_asset(sym, k)) if EVAL_START <= pd.Timestamp(r.t) < EVAL_END]
        s = summary(sr)
        sens[str(k)] = {"mean_net_pct": s["mean_net_pct"], "profit_factor": s["profit_factor"], "filled": s["filled"]}
    triples = [((frow.loc[x["t"], "close"] - by_t[x["t"]].limit) / frow.loc[x["t"], "atr"],
                (by_t[x["t"]].limit - by_t[x["t"]].stop) / frow.loc[x["t"], "atr"],
                (by_t[x["t"]].target - by_t[x["t"]].limit) / frow.loc[x["t"], "atr"], by_t[x["t"]].entry_bars) for x in ev]
    f_eval = f[(f["t"] >= EVAL_START) & (f["t"] < EVAL_END)]
    rule_mean = float(np.mean([r.net for r in eres if r.filled])) if any(r.filled for r in eres) else -np.inf
    rb = random_baseline(f_eval, triples, len(eres), m, costs, rule_mean, seed)
    probs = prob_eval(rows)
    return {"asset": sym, "config": cfg["id"], "family": cfg["family"], "params": cfg, "summary": st, "no_data": no_data,
            "windows": per_window, "cost_sensitivity": sens, "random": rb, "probabilities": probs}


def criteria(r: dict) -> dict:
    s = r["summary"]
    pos = sum(1 for w in r["windows"] if w["filled"] and (w["mean_net_pct"] or 0) > 0)
    b2 = r["probabilities"]["p_target_first"].get("brier_skill")
    b3 = r["probabilities"]["p_net_win"].get("brier_skill")
    c = {"filled_ge_40": s["filled"] >= 40,
         "mean_net_gt_0": (s["mean_net_pct"] or -1) > 0,
         "pf_gt_1_1": (s["profit_factor"] or 0) > 1.1,
         "positive_windows_ge_3": pos >= 3,
         "holm_p_lt_0_05": r["random"]["p_holm"] < 0.05,
         "brier_skill_gt_0": (b2 is not None and b2 > 0) or (b3 is not None and b3 > 0)}
    c = {k: bool(v) for k, v in c.items()}  # plain booleans in the JSON
    c["positive_windows"] = pos
    c["qualified"] = all(v for k, v in c.items() if k != "positive_windows")
    return c


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def main(argv) -> int:
    t0 = time.time()
    results, fps, baselines = [], {}, {}
    for ai, sym in enumerate(("BTCUSDT", "SOLUSDT")):
        f, m, fps[sym] = load_dev(sym)
        # audit: phase-1 baseline reproduced on holdout-free data must equal the stored phase-1 numbers
        dev = f[(f["t"] >= rules.DEV_START) & (f["t"] < EVAL_END)]
        p1 = summary(run([generic(r) for _, r in dev.iterrows()], m, Costs.for_asset(sym)))
        ev = f[(f["t"] >= EVAL_START) & (f["t"] < EVAL_END)]
        bl = {}
        for name, fr, mk in (("always_limit", ev, False), ("always_market", ev, True), ("trend_limit", ev[ev["close"] > ev["ema200"]], False)):
            rs = run([generic(r, market=mk) for _, r in fr.iterrows()], m, Costs.for_asset(sym))
            bl[name] = block_stats(rs, [pd.Timestamp(r.t).strftime("%Y-%m") for r in rs])
        c = ev["close"]
        bl["buy_hold_pct"] = round(100 * (c.iloc[-1] / c.iloc[0] - 1), 1)
        baselines[sym] = {"phase1_always_limit_reproduced_on_holdout_free_data": {k: p1[k] for k in ("filled", "mean_net_pct", "profit_factor")},
                          "eval_window": bl}
        for ci, cfg in enumerate(rules.configs()):
            results.append(evaluate(sym, f, m, cfg, SEED + 100 * ai + ci))
            print(sym, cfg["id"], round(time.time() - t0), "s", file=sys.stderr)
    adj = holm([r["random"]["p_value"] for r in results])
    for r, a in zip(results, adj):
        r["random"]["p_holm"] = a
        r["criteria"] = criteria(r)
    sel = {}
    for sym in ("BTCUSDT", "SOLUSDT"):
        q = [r for r in results if r["asset"] == sym and r["criteria"]["qualified"]]
        q.sort(key=lambda r: (r["summary"]["mean_net_ci_pct"] or (-1e9,))[0], reverse=True)
        sel[sym] = [r["config"] for r in q[:3]]
    OUT.mkdir(exist_ok=True)
    (OUT / "phase2_results.json").write_text(json.dumps({"engine": "te-0.1.0", "eval": [str(EVAL_START), str(EVAL_END)],
        "baselines": baselines, "results": results}, indent=1, ensure_ascii=False, default=str))
    files = {n: sha(HERE / n) for n in ("sim.py", "rules.py", "metrics.py", "phase2.py", "data.py", "PREREG.md")}
    (OUT / "phase2_selection.json").write_text(json.dumps({"engine": "te-0.1.0", "selected": sel, "file_sha256_16": files,
        "data_fingerprints": fps, "holdout_opened": False}, indent=1))
    lines = ["| asset | config | orders | filled | fill % | target-first % | net-win % | mean net % [CI] | PF [CI] | windows + | p | p Holm | BSS tgt | BSS win | cost×2 PF | qualified |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        s, c, p = r["summary"], r["criteria"], r["probabilities"]
        pct = lambda v: "—" if v is None else f"{100 * v:.0f}"
        lines.append(f"| {r['asset'][:3]} | {r['config']} | {s['orders']} | {s['filled']} | {pct(s['fill_rate'])} | {pct(s['p_target_first'])} | "
                     f"{pct(s['p_net_win'])} | {s['mean_net_pct']} {s['mean_net_ci_pct']} | {s['profit_factor']} {s['profit_factor_ci']} | "
                     f"{c['positive_windows']}/4 | {r['random']['p_value']} | {r['random']['p_holm']} | "
                     f"{p['p_target_first'].get('brier_skill')} | {p['p_net_win'].get('brier_skill')} | "
                     f"{r['cost_sensitivity']['2.0']['profit_factor']} | {'YES' if c['qualified'] else 'no'} |")
    (OUT / "phase2_table.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"selected": sel, "seconds": round(time.time() - t0)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
