"""PAXG/USDT (Binance) stage 2: three tests, each on its own. Research only — no recommendation follows from any of them.

PRE-REGISTERED 2026-11-16, committed before any predictive result on real data was seen (stage 1 looked only at
coverage, liquidity, spread and the level of the premium). One attempt each; nothing below is tuned on the results.
Gold (XAU/USD, Dukascopy H1) is used only through CLOSED bars; while gold is closed its last close is the reference.

Test A — price range on PAXG alone: goldquant/price_range.py unchanged ("crypto" kind: 4 / 24 / 168 hourly bars),
          same baselines and gates G1-G4. Gold's result is NOT transferred.

Test B — premium as a signal (spot PAXG, long only: spot cannot be shorted).
  premium p = 100 * ln(PAXG close / XAU close) on the hours both trade (same bar open time).
  z = (p - mean of p over the previous 30 days) / std over the previous 30 days (at least 200 hours), known at t.
  Entry: buy PAXG at the close of an hour with z <= -1.5 (PAXG at a discount); exit 24 hours later at PAXG's close.
  Trades do not overlap. Net return = gross - 0.24 % (0.1 % taker fee each way + 0.02 % slippage each way).
  Baseline: the 24 h PAXG return after EVERY eligible hour (same hours, same cost) — does the discount add anything?
  Split: first 80 % of time = development, last 20 % = holdout (nothing is fitted; the split only guards against luck).
  Qualifies only if ALL: B1 development net mean > 0 with 99 % block-bootstrap CI (weekly blocks) above 0;
  B2 development mean minus baseline mean > 0 with its 99 % CI above 0; B3 holdout net mean > 0 and above the
  baseline; B4 at least 100 development trades.
  Descriptive only: correlation of z with the next 24 h PAXG-minus-XAU return (predictive power BEFORE costs), and the
  mean next-24 h PAXG return after z >= +1.5 (what a holder would have avoided).

Test C — weekend: does PAXG's move while gold is closed anticipate gold's reopening gap?
  For every Friday close of gold (a gap of more than 24 h between consecutive gold bars, the last bar on a Friday):
  gap = 100 * ln(first gold open after the weekend / last Friday close); w = 100 * ln(PAXG close at the reopening
  hour / PAXG close at gold's Friday close hour). Both must exist.
  Model: gap = a + b * w (OLS), walk-forward by calendar year from the third year (fit on all earlier weekends);
  the last 20 % of weekends is a holdout fitted on everything before it.
  Skill = 1 - MSE(model) / MSE(predicting a zero gap). Direction hit rate vs the majority sign of the training gaps.
  Qualifies only if ALL: C1 walk-forward skill > 0 with 99 % bootstrap CI (over weekends) above 0; C2 holdout skill > 0;
  C3 walk-forward hit rate above the baseline hit rate; C4 at least 150 walk-forward weekends.
  Use, if it qualifies: a descriptive note for gold users before Monday's open — never a trade.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VERSION = "paxg-study-0.1.0"
Z_IN, ROLL_DAYS, ROLL_MIN = -1.5, 30, 200
HOLD_H = 24
COST_PCT = 0.24
CI_LEVEL = 99.0
HOLDOUT_FRAC = 0.2
MIN_TRADES, MIN_WEEKENDS = 100, 150


def _boot_mean_ci(x: np.ndarray, groups: np.ndarray, level=CI_LEVEL, n=2000, seed=5):
    ids, inv = np.unique(groups, return_inverse=True)
    s, c = np.bincount(inv, weights=x), np.bincount(inv)
    rng = np.random.default_rng(seed)
    d = rng.integers(0, len(ids), size=(n, len(ids)))
    b = s[d].sum(1) / c[d].sum(1)
    a = (100 - level) / 2
    return float(np.percentile(b, a)), float(np.percentile(b, 100 - a))


def premium_frame(paxg: pd.DataFrame, xau: pd.DataFrame) -> pd.DataFrame:
    j = pd.concat([paxg["close"].astype(float).rename("paxg"), xau["close"].astype(float).rename("xau")],
                  axis=1, join="inner").dropna()
    j["p"] = 100 * np.log(j["paxg"] / j["xau"])
    r = j["p"].rolling(f"{ROLL_DAYS}D", min_periods=ROLL_MIN)
    j["z"] = (j["p"] - r.mean()) / r.std()
    pc = paxg["close"].astype(float)
    fut = pc.reindex(j.index + pd.Timedelta(hours=HOLD_H)).to_numpy()
    j["ret24"] = 100 * np.log(fut / j["paxg"].to_numpy())
    xf = xau["close"].astype(float).reindex(j.index + pd.Timedelta(hours=HOLD_H)).to_numpy()
    j["rel24"] = j["ret24"] - 100 * np.log(xf / j["xau"].to_numpy())
    return j


def premium_test(paxg: pd.DataFrame, xau: pd.DataFrame) -> dict:
    j = premium_frame(paxg, xau).dropna(subset=["z", "ret24"])
    out = {"version": VERSION, "test": "B premium signal", "hours": int(len(j)), "qualified": False}
    if len(j) < 2000:
        out["reason"] = "not enough overlapping hours"
        return out
    cut = j.index[int(len(j) * (1 - HOLDOUT_FRAC))]

    def trades(d: pd.DataFrame) -> pd.DataFrame:
        rows, free = [], None
        for t, r in d[d["z"] <= Z_IN].iterrows():
            if free is not None and t < free:
                continue
            rows.append((t, r["ret24"]))
            free = t + pd.Timedelta(hours=HOLD_H)
        return pd.DataFrame(rows, columns=["t", "gross"]).set_index("t")

    def block(d: pd.DataFrame) -> dict:
        tr = trades(d)
        net = tr["gross"].to_numpy() - COST_PCT
        base = d["ret24"].to_numpy() - COST_PCT
        wk = lambda idx: pd.DatetimeIndex(idx).as_unit("ns").asi8 // (7 * 86_400 * 10**9)  # noqa: E731
        res = {"trades": int(len(tr)), "net_mean_pct": round(float(net.mean()), 4) if len(net) else None,
               "win_rate": round(float((net > 0).mean()), 4) if len(net) else None,
               "baseline_net_mean_pct": round(float(base.mean()), 4)}
        if len(net) >= 10:
            res["net_ci99"] = [round(v, 4) for v in _boot_mean_ci(net, wk(tr.index))]
            # difference vs baseline: trade return minus the mean baseline return of the same week
            bw = pd.Series(base, index=d.index).groupby(wk(d.index)).mean()
            diff = net - bw.reindex(wk(tr.index)).to_numpy()
            ok = np.isfinite(diff)
            res["diff_vs_baseline_pct"] = round(float(diff[ok].mean()), 4)
            res["diff_ci99"] = [round(v, 4) for v in _boot_mean_ci(diff[ok], wk(tr.index)[ok])]
        return res

    dev, ho = block(j[j.index < cut]), block(j[j.index >= cut])
    zz = j.dropna(subset=["rel24"])
    out.update({
        "period": f"{j.index[0].date()} -> {j.index[-1].date()}", "holdout_from": str(cut.date()),
        "development": dev, "holdout": ho,
        "descriptive": {
            "corr_z_next24_rel_return": round(float(np.corrcoef(zz["z"], zz["rel24"])[0, 1]), 4) if len(zz) > 100 else None,
            "mean_next24_paxg_after_z_ge_1.5_pct": round(float(j.loc[j["z"] >= 1.5, "ret24"].mean()), 4)
            if (j["z"] >= 1.5).any() else None}})
    g = {"B1 development net > 0 (99% CI)": bool(dev.get("net_ci99") and dev["net_ci99"][0] > 0),
         "B2 beats baseline (99% CI)": bool(dev.get("diff_ci99") and dev["diff_ci99"][0] > 0),
         "B3 holdout net > 0 and above baseline": bool(ho.get("net_mean_pct") is not None and ho["net_mean_pct"] > 0
                                                      and ho["net_mean_pct"] > ho["baseline_net_mean_pct"]),
         "B4 >= 100 development trades": dev["trades"] >= MIN_TRADES}
    out["gates"], out["qualified"] = g, all(g.values())
    out["reason"] = "qualified" if out["qualified"] else "failed: " + ", ".join(k.split()[0] for k, v in g.items() if not v)
    return out


def weekend_frame(paxg: pd.DataFrame, xau: pd.DataFrame) -> pd.DataFrame:
    idx = xau.index
    pc = paxg["close"].astype(float)
    rows = []
    for i in range(len(idx) - 1):
        a, b = idx[i], idx[i + 1]
        if (b - a) <= pd.Timedelta(hours=24) or a.dayofweek != 4:
            continue
        t_fri, t_re = a + pd.Timedelta(hours=1), b  # Friday close time, reopening (first bar open)
        xf, xr = float(xau["close"].iloc[i]), float(xau["open"].iloc[i + 1])
        pf, pr = pc.get(t_fri - pd.Timedelta(hours=1)), pc.get(t_re - pd.Timedelta(hours=1))  # PAXG bars ending then
        if pf is None or pr is None or not np.isfinite(pf) or not np.isfinite(pr):
            continue
        rows.append({"t": t_re, "gap": 100 * np.log(xr / xf), "w": 100 * np.log(pr / pf)})
    return pd.DataFrame(rows).set_index("t") if rows else pd.DataFrame(columns=["gap", "w"])


def weekend_test(paxg: pd.DataFrame, xau: pd.DataFrame) -> dict:
    d = weekend_frame(paxg, xau)
    out = {"version": VERSION, "test": "C weekend gap", "weekends": int(len(d)), "qualified": False}
    if len(d) < 60:
        out["reason"] = "not enough weekends"
        return out
    cut = d.index[int(len(d) * (1 - HOLDOUT_FRAC))]

    def fit(tr):
        X = np.column_stack([np.ones(len(tr)), tr["w"].to_numpy()])
        coef, *_ = np.linalg.lstsq(X, tr["gap"].to_numpy(), rcond=None)
        maj = 1.0 if (tr["gap"] > 0).mean() >= 0.5 else -1.0
        return coef, maj

    preds = []
    years = sorted(set(d.index[d.index < cut].year))[2:]
    for yr in years:
        y0 = pd.Timestamp(f"{yr}-01-01", tz="UTC")
        tr, te = d[d.index < y0], d[(d.index >= y0) & (d.index < min(pd.Timestamp(f"{yr + 1}-01-01", tz="UTC"), cut))]
        if len(tr) < 30 or te.empty:
            continue
        coef, maj = fit(tr)
        preds.append(te.assign(pred=coef[0] + coef[1] * te["w"], maj=maj))
    if not preds:
        out["reason"] = "no complete fold"
        return out
    wf = pd.concat(preds)
    coef, maj = fit(d[d.index < cut])
    ho = d[d.index >= cut].assign(pred=lambda x: coef[0] + coef[1] * x["w"], maj=maj)

    def stats(x: pd.DataFrame) -> dict:
        e_m, e_0 = (x["gap"] - x["pred"]) ** 2, x["gap"] ** 2
        hit = float((np.sign(x["pred"]) == np.sign(x["gap"])).mean())
        base = float((np.sign(x["maj"]) == np.sign(x["gap"])).mean())
        return {"n": int(len(x)), "skill": round(float(1 - e_m.mean() / e_0.mean()), 4), "hit_rate": round(hit, 4),
                "baseline_hit_rate": round(base, 4), "mean_abs_gap_pct": round(float(x["gap"].abs().mean()), 4),
                "corr_w_gap": round(float(np.corrcoef(x["w"], x["gap"])[0, 1]), 4)}

    W, H = stats(wf), stats(ho)
    e0 = (wf["gap"] ** 2).to_numpy()
    em = ((wf["gap"] - wf["pred"]) ** 2).to_numpy()
    rng = np.random.default_rng(9)
    k = rng.integers(0, len(wf), size=(2000, len(wf)))
    boot = 1 - em[k].mean(1) / e0[k].mean(1)
    ci = [round(float(np.percentile(boot, 0.5)), 4), round(float(np.percentile(boot, 99.5)), 4)]
    g = {"C1 walk-forward skill > 0 (99% CI)": ci[0] > 0, "C2 holdout skill > 0": H["skill"] > 0,
         "C3 hit rate above baseline": W["hit_rate"] > W["baseline_hit_rate"],
         "C4 >= 150 walk-forward weekends": W["n"] >= MIN_WEEKENDS}
    out.update({"period": f"{d.index[0].date()} -> {d.index[-1].date()}", "holdout_from": str(cut.date()),
                "walk_forward": W, "skill_ci99": ci, "holdout": H,
                "final_fit": {"a": round(float(coef[0]), 5), "b": round(float(coef[1]), 5)}, "gates": g,
                "qualified": all(g.values())})
    out["reason"] = "qualified" if out["qualified"] else "failed: " + ", ".join(k.split()[0] for k, v in g.items() if not v)
    return out
