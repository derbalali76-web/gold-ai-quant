"""te-0.2.0 development-data evaluation (PREREG_v2.md). Holdout bars are removed before anything is built.
Outputs: reports/v2_results.json, reports/v2_table.md, reports/v2_selection.json
Run: python -m trade_engine.phase2_v2
"""
from __future__ import annotations
import hashlib, json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import data, rules_v2 as R
from .metrics import summary, wilson, pf, month_block_boot, brier_skill, reliability
from .rules import HOLDOUT_START, EMBARGO
from .sim import Costs, Market, run, simulate
from .phase2 import holm

HERE = Path(__file__).resolve().parent
OUT = HERE / "reports"
EVAL_START = pd.Timestamp("2022-01-01", tz="UTC")
EVAL_END = HOLDOUT_START - EMBARGO
WINDOWS = [(pd.Timestamp(a, tz="UTC"), min(pd.Timestamp(b, tz="UTC"), EVAL_END)) for a, b in
           (("2022-01-01", "2023-01-01"), ("2023-01-01", "2024-01-01"), ("2024-01-01", "2025-01-01"), ("2025-01-01", "2025-11-15"))]
DRAWS, BOOT, SEED = 1000, 2000, 20261119
PFEAT = {"H1": "funding_pct", "H2": "doi8_pct", "H3": "tbs12_pct"}


def load(sym):
    h1, q = data.load(sym, "1h"), data.load(sym, "15m")
    h1, q = h1[h1.index < HOLDOUT_START], q[q.index < HOLDOUT_START]
    m = Market(q, h1)
    assert m.end <= HOLDOUT_START
    f = R.features(sym, h1, HOLDOUT_START)
    f["atr_terc"] = np.select([f["atrp_pct"] < 1 / 3, f["atrp_pct"] < 2 / 3], ["lo", "mid"], "hi")
    f.loc[f["atrp_pct"].isna(), "atr_terc"] = "na"
    return f.reset_index(drop=True), m


def placed(f, sig, cfg, m, costs, start, end):
    rows = f[(f["t"] >= start) & (f["t"] < end) & sig.reindex(f.index, fill_value=False)]
    ods = [o for _, r in rows.iterrows() if (o := R.order_at(r, cfg)) is not None]
    return run(ods, m, costs)


def mstats(res):
    s = summary(res)
    fl = [r for r in res if r.filled]
    net = np.array([r.net for r in fl])
    mo = np.array([pd.Timestamp(r.t).strftime("%Y-%m") for r in fl])
    ci = month_block_boot(mo, net, np.mean, n=BOOT)
    s["mean_net_ci_pct"] = ci and (round(100 * ci[0], 4), round(100 * ci[1], 4))
    s["profit_factor_ci"] = month_block_boot(mo, net, pf, n=BOOT)
    return s


def split(res, f, key):
    lab = dict(zip(f["t"].astype(str), f[key]))
    out = {}
    for r in res:
        out.setdefault(lab.get(str(pd.Timestamp(r.t)), "na"), []).append(r)
    return {k: {x: summary(v)[x] for x in ("orders", "filled", "p_target_first", "p_net_win", "mean_net_pct", "profit_factor")}
            for k, v in sorted(out.items())}


def per_window(res):
    out = []
    for a, b in WINDOWS:
        s = summary([r for r in res if a <= pd.Timestamp(r.t) < b])
        out.append({"window": f"{a.date()}..{b.date()}", "filled": s["filled"], "mean_net_pct": s["mean_net_pct"], "profit_factor": s["profit_factor"]})
    return out


def pool_nets(f_eval, cfg, m, costs):
    nets = np.full(len(f_eval), np.nan)
    for i, (_, r) in enumerate(f_eval.iterrows()):
        o = R.order_at(r, cfg)
        if o is None:
            continue
        x = simulate(o, m, costs)
        if x.outcome != "NO_DATA":
            nets[i] = x.net if x.filled else np.inf
    return nets


def p_random(nets, n, rule_mean, rng, strata=None, rule_strata=None):
    if n < 10 or not np.isfinite(rule_mean):
        return 1.0, None
    valid = ~np.isnan(nets)
    means = []
    for _ in range(DRAWS):
        if strata is None:
            idx = rng.choice(np.where(valid)[0], size=min(n, int(valid.sum())), replace=False)
        else:
            idx = []
            for st in rule_strata:
                cand = np.where(valid & (strata == st))[0]
                if len(cand):
                    idx.append(rng.choice(cand))
            idx = np.array(idx, int)
        s = nets[idx]
        s = s[np.isfinite(s)]
        if len(s):
            means.append(s.mean())
    means = np.array(means)
    return (1 + int((means >= rule_mean).sum())) / (1 + len(means)), [round(100 * float(np.percentile(means, q)), 4) for q in (5, 50, 95)]


def p_ablation(res, abl, rng):
    """Joint circular 3-month block bootstrap of (rule mean - ablation mean) over the same calendar months."""
    a = [(pd.Timestamp(r.t).strftime("%Y-%m"), r.net) for r in res if r.filled]
    b = [(pd.Timestamp(r.t).strftime("%Y-%m"), r.net) for r in abl if r.filled]
    if len(a) < 10 or len(b) < 10:
        return 1.0, None
    months = sorted({k for k, _ in a} | {k for k, _ in b})
    ga = {k: [v for kk, v in a if kk == k] for k in months}
    gb = {k: [v for kk, v in b if kk == k] for k in months}
    nm, diffs = len(months), []
    for _ in range(BOOT):
        sa, sb, got = [], [], 0
        while got < nm:
            s0 = int(rng.integers(0, nm))
            for d in range(3):
                k = months[(s0 + d) % nm]
                sa += ga[k]; sb += gb[k]
            got += 3
        if sa and sb:
            diffs.append(np.mean(sa) - np.mean(sb))
    diffs = np.array(diffs)
    return (1 + int((diffs <= 0).sum())) / (1 + len(diffs)), round(100 * float(np.mean([v for _, v in a]) - np.mean([v for _, v in b])), 4)


def probs(f, res_all, hyp):
    lab = f.set_index(f["t"].astype(str))
    rows = []
    for r in res_all:
        x = lab.loc[str(pd.Timestamp(r.t))]
        rows.append({"t": pd.Timestamp(r.t), "x": [x["atrp"], x["ret24"], x["ret90d"], x[PFEAT[hyp]]],
                     "p_fill": float(r.filled), "p_target_first": float(r.outcome == "TARGET"), "p_net_win": float(r.filled and r.net > 0),
                     "filled": r.filled})
    out = {}
    for key in ("p_fill", "p_target_first", "p_net_win"):
        P, B, Y = [], [], []
        for a, b in WINDOWS:
            tr = [z for z in rows if z["t"] < a - EMBARGO and (key == "p_fill" or z["filled"]) and np.all(np.isfinite(z["x"]))]
            te = [z for z in rows if a <= z["t"] < b and (key == "p_fill" or z["filled"])]
            if not te:
                continue
            ytr = np.array([z[key] for z in tr], float)
            base = float(ytr.mean()) if len(ytr) else 0.5
            ok = np.array([np.all(np.isfinite(z["x"])) for z in te])
            p = np.full(len(te), base)
            if len(ytr) >= 30 and 0 < ytr.sum() < len(ytr) and ok.any():
                mdl = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000)).fit(np.array([z["x"] for z in tr]), ytr)
                p[ok] = mdl.predict_proba(np.array([z["x"] for i, z in enumerate(te) if ok[i]]))[:, 1]
            P.append(p); B.append(np.full(len(te), base)); Y.append(np.array([z[key] for z in te], float))
        if not P:
            out[key] = {"n": 0, "brier_skill": None, "calibrated": False}
            continue
        p, bs, y = np.concatenate(P), np.concatenate(B), np.concatenate(Y)
        rel = reliability(p, y)
        citl = abs(float(p.mean() - y.mean()))
        bins_ok = all(abs(b["mean_p"] - b["observed"]) <= 0.10 for b in rel if b["n"] >= 20)
        out[key] = {"n": int(len(y)), "observed": round(float(y.mean()), 4), "observed_ci": wilson(int(y.sum()), len(y)),
                    "brier": round(float(((p - y) ** 2).mean()), 4), "brier_base": round(float(((bs - y) ** 2).mean()), 4),
                    "brier_skill": brier_skill(p, bs, y), "calibration_in_the_large": round(citl, 4),
                    "calibrated": bool(citl <= 0.05 and bins_ok), "reliability": rel}
    return out


def evaluate(sym, f, m, cfg, seed):
    rng = np.random.default_rng(seed)
    c = Costs.for_asset(sym)
    sig = R.signal(f, cfg["hyp"], cfg["q"])
    res_all = placed(f, sig, cfg, m, c, pd.Timestamp("2021-01-01", tz="UTC"), EVAL_END)
    res = [r for r in res_all if pd.Timestamp(r.t) >= EVAL_START]
    abl = placed(f, R.signal(f, cfg["hyp"], cfg["q"], ablation=True), cfg, m, c, EVAL_START, EVAL_END)
    st = mstats(res)
    rule_mean = float(np.mean([r.net for r in res if r.filled])) if any(r.filled for r in res) else -np.inf
    fe = f[(f["t"] >= EVAL_START) & (f["t"] < EVAL_END)].reset_index(drop=True)
    nets = pool_nets(fe, cfg, m, c)
    pa, da = p_random(nets, len(res), rule_mean, rng)
    strata = (fe["regime"] + "|" + fe["atr_terc"]).to_numpy()
    lab = dict(zip(fe["t"].astype(str), strata))
    pb, db = p_random(nets, len(res), rule_mean, rng, strata, [lab.get(str(pd.Timestamp(r.t)), "na") for r in res])
    pc, dc = p_ablation(res, abl, rng)
    sens = {str(k): {x: summary([r for r in placed(f, sig, cfg, m, Costs.for_asset(sym, k), EVAL_START, EVAL_END)])[x]
                     for x in ("filled", "mean_net_pct", "profit_factor")} for k in (0.75, 2.0)}
    return {"asset": sym, "config": cfg["id"], "params": cfg, "summary": st, "no_data": sum(r.outcome == "NO_DATA" for r in res),
            "windows": per_window(res), "regimes": split(res, f, "regime"), "ablation": {"summary": mstats(abl), "windows": per_window(abl)},
            "tests": {"random_p": pa, "random_mean_pct_p5_p50_p95": da, "regime_random_p": pb, "regime_random_mean_pct_p5_p50_p95": db,
                      "ablation_p": pc, "rule_minus_ablation_mean_pct": dc},
            "cost_sensitivity": sens, "probabilities": probs(f, res_all, cfg["hyp"])}


def criteria(r):
    s, t = r["summary"], r["tests"]
    win_pos = sum(1 for w in r["windows"] if w["filled"] and (w["mean_net_pct"] or 0) > 0)
    better = sum(1 for w, a in zip(r["windows"], r["ablation"]["windows"])
                 if w["filled"] and a["filled"] and (w["mean_net_pct"] or -9) > (a["mean_net_pct"] or -9))
    regs = [v for k, v in r["regimes"].items() if k in ("up", "down", "range") and v["filled"] >= 20]
    pr = r["probabilities"]
    prob_ok = any((pr[k].get("brier_skill") or 0) > 0 and pr[k].get("calibrated") for k in ("p_target_first", "p_net_win"))
    ci = s["mean_net_ci_pct"]
    c = {"1_filled_ge_40": s["filled"] >= 40,
         "2_mean_gt_0_and_pf_gt_1_15": (s["mean_net_pct"] or -1) > 0 and (s["profit_factor"] or 0) > 1.15,
         "3_mean_ci_lower_gt_0": bool(ci) and ci[0] > 0,
         "4_positive_in_3_of_4_windows": win_pos >= 3,
         "5_beats_random_holm": t["random_p_holm"] < 0.05,
         "6_beats_regime_random_holm": t["regime_random_p_holm"] < 0.05,
         "7_beats_price_only_ablation": t["ablation_p_holm"] < 0.05 and better >= 3,
         "8_positive_in_every_regime_with_20": bool(regs) and all((v["mean_net_pct"] or -1) > 0 for v in regs),
         "9_pf_gt_1_with_costs_x2": (r["cost_sensitivity"]["2.0"]["profit_factor"] or 0) > 1.0,
         "10_calibrated_probability_with_skill": prob_ok}
    c = {k: bool(v) for k, v in c.items()}
    c["qualified"] = all(c.values())
    c["windows_positive"], c["windows_better_than_ablation"] = win_pos, better
    return c


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


def main(argv):
    t0 = time.time()
    results = []
    for ai, sym in enumerate(("BTCUSDT", "SOLUSDT")):
        f, m = load(sym)
        for ci, cfg in enumerate(R.configs()):
            results.append(evaluate(sym, f, m, cfg, SEED + 100 * ai + ci))
            print(sym, cfg["id"], round(time.time() - t0), "s", file=sys.stderr, flush=True)
    for key in ("random_p", "regime_random_p", "ablation_p"):
        for r, a in zip(results, holm([r["tests"][key] for r in results])):
            r["tests"][key + "_holm"] = a
    for r in results:
        r["criteria"] = criteria(r)
    sel = {}
    for sym in ("BTCUSDT", "SOLUSDT"):
        q = sorted([r for r in results if r["asset"] == sym and r["criteria"]["qualified"]],
                   key=lambda r: r["summary"]["mean_net_ci_pct"][0], reverse=True)
        sel[sym] = [r["config"] for r in q[:2]]
    OUT.mkdir(exist_ok=True)
    (OUT / "v2_results.json").write_text(json.dumps({"engine": "te-0.2.0", "eval": [str(EVAL_START), str(EVAL_END)], "results": results},
                                                    indent=1, default=str))
    files = {n: sha(HERE / n) for n in ("sim.py", "rules_v2.py", "metrics.py", "phase2_v2.py", "phase2.py", "data.py", "PREREG_v2.md")}
    (OUT / "v2_selection.json").write_text(json.dumps({"engine": "te-0.2.0", "selected": sel, "file_sha256_16": files,
                                                       "holdout_opened": False}, indent=1))
    lines = ["| asset | config | filled | mean net % [CI] | PF | win+ | p rnd (Holm) | p regime (Holm) | p ablation (Holm) | criteria passed | qualified |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        s, t, c = r["summary"], r["tests"], r["criteria"]
        npass = sum(v for k, v in c.items() if k[0].isdigit())
        lines.append(f"| {r['asset'][:3]} | {r['config']} | {s['filled']} | {s['mean_net_pct']} {s['mean_net_ci_pct']} | {s['profit_factor']} | "
                     f"{c['windows_positive']}/4 | {t['random_p']} ({t['random_p_holm']}) | {t['regime_random_p']} ({t['regime_random_p_holm']}) | "
                     f"{t['ablation_p']} ({t['ablation_p_holm']}) | {npass}/10 | {'YES' if c['qualified'] else 'no'} |")
    (OUT / "v2_table.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"selected": sel, "seconds": round(time.time() - t0)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
