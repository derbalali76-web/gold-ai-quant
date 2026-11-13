"""Walk-forward backtester (MASTER "Backtest and validation" + V2 §6).

- Models are refit every `refit_days` using only outcomes KNOWN at the refit time.
- Decision at the close of bar i; entry at the OPEN of bar i+1, worsened by half-spread + slippage.
- SL/TP ordering inside a bar is conservative (both touched => SL). Timeout exits at the close of the last bar
  inside the wall-clock horizon, paying half-spread. One position at a time (no overlapping trades).
- Session closed / daily break / last 4h before weekly close are skipped, as in the live engine.
- The final 20 % of the timeline is a HOLDOUT: it is only evaluated with final=True, and each such run is
  recorded so repeated peeking is visible.
- A simple baseline (same direction rule, no model gate) is always reported alongside.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import model as M
from . import path as P
from .bias import bias_score, direction as bias_direction
from .features import frame_features
from .model import wilson
from .regime import classify, volatility_regime
from .risk import EST_SLIPPAGE, EST_SPREAD

H = 240
HB = H // 15


@dataclass
class Trade:
    decision_time: str
    direction: int
    entry: float
    stop: float
    target: float
    exit_time: str
    exit_price: float
    outcome: int  # +1 target, -1 stop, 0 timeout
    pnl: float  # USD/oz after costs
    risk: float
    p_tp: float | None
    p_sl: float | None
    vol_regime: str


@dataclass
class Report:
    period: str
    start: str
    end: str
    opportunities: int
    signals: int
    abstention_rate: float
    trades: int
    win_rate: float | None
    win_rate_ci95: list | None
    profit_factor: float | None
    ev_per_trade: float | None
    ev_ci95: list | None
    total_pnl: float
    max_drawdown: float
    sharpe_per_trade_annualized: float | None
    brier_multiclass: float | None
    by_regime: dict = field(default_factory=dict)
    baseline: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def _m30_dist(m15: pd.DataFrame) -> pd.Series:
    m30 = m15.resample("30min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    f = frame_features(m30)["dist_ema20_atr"]
    f.index = f.index + pd.Timedelta(minutes=30)
    return f


def _simulate(m15, table, signal_idx, dirs, probs, min_edge, vreg, em=None):
    hi, lo, op, cl = (m15[k].to_numpy() for k in ("high", "low", "open", "close"))
    t_open = m15.index
    tmin = (t_open.as_unit("ns").asi8 // 60_000_000_000)
    atr = table["atr"].to_numpy()
    trades, busy_until = [], -1
    sess = table["session"].to_numpy()
    vr = table["vol_ratio"].to_numpy()
    for i, d, pr in zip(signal_idx, dirs, probs):
        if em is None:
            half, slip, delay = EST_SPREAD / 2, EST_SLIPPAGE, 1
        else:  # Execution Reality Simulator
            half, slip, delay = em.spread(sess[i], vr[i]) / 2, em.slippage(atr[i]), em.entry_delay_bars()
        if i <= busy_until or i + delay >= len(cl):
            continue
        e = i + delay
        risk = 2.0 * atr[i]
        ref = cl[i]  # levels are set from the decision price, exactly like the live engine
        entry = op[e] + d * (half + slip)
        stop, target = ref - d * risk, ref + d * risk
        end_t = tmin[i] + 15 + H  # decision time + horizon
        outcome, exit_p, j = 0, None, e
        while j < len(cl) and tmin[j] + 15 <= end_t:
            sl_hit = lo[j] <= stop if d > 0 else hi[j] >= stop
            tp_hit = hi[j] >= target if d > 0 else lo[j] <= target
            if sl_hit:  # a gap through the stop fills at the (worse) open
                gap_px = min(stop, op[j]) if d > 0 else max(stop, op[j])
                outcome, exit_p = -1, gap_px - d * slip
                break
            if tp_hit:
                outcome, exit_p = 1, target
                break
            j += 1
        if exit_p is None:
            j = min(j - 1, len(cl) - 1)
            if j < e:
                continue
            exit_p = cl[j] - d * half
        pnl = d * (exit_p - entry)
        trades.append(Trade(str(t_open[i] + pd.Timedelta(minutes=15)), int(d), round(entry, 2), round(stop, 2),
                            round(target, 2), str(t_open[j] + pd.Timedelta(minutes=15)), round(float(exit_p), 2),
                            outcome, round(float(pnl), 3), round(float(risk), 3),
                            None if pr is None else float(pr[0]), None if pr is None else float(pr[1]), vreg.get(i, "?")))
        busy_until = j
    return trades


def _metrics(trades: list[Trade], opportunities: int, signals: int, period: str, start, end, rng) -> Report:
    pnl = np.array([t.pnl for t in trades])
    n = len(trades)
    warnings = []
    if n < 300:
        warnings.append(f"عدد الصفقات {n} أقل من 300 — النتائج غير موثوقة إحصائياً")
    wins = int(sum(t.outcome == 1 for t in trades))
    gp, gl = pnl[pnl > 0].sum() if n else 0.0, -pnl[pnl < 0].sum() if n else 0.0
    eq = np.cumsum(pnl) if n else np.array([0.0])
    dd = float(np.max(np.maximum.accumulate(eq) - eq)) if n else 0.0
    ev_ci = None
    if n >= 20:
        boots = [rng.choice(pnl, n, replace=True).mean() for _ in range(1000)]
        ev_ci = [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)]
    briers = []
    for t in trades:
        if t.p_tp is not None:
            p = np.array([t.p_tp, t.p_sl, 1 - t.p_tp - t.p_sl])
            y = np.array([t.outcome == 1, t.outcome == -1, t.outcome == 0], dtype=float)
            briers.append(float(np.sum((p - y) ** 2)))
    sharpe = None
    if n >= 30 and pnl.std() > 0:
        span_years = max((pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25, 1e-6)
        sharpe = round(float(pnl.mean() / pnl.std() * np.sqrt(n / span_years)), 3)
    by = {}
    for reg in sorted({t.vol_regime for t in trades}):
        sub = [t for t in trades if t.vol_regime == reg]
        by[reg] = {"trades": len(sub), "win_rate": round(sum(t.outcome == 1 for t in sub) / len(sub), 4),
                   "ev": round(float(np.mean([t.pnl for t in sub])), 3)}
    ci = wilson(wins, n) if n else None
    return Report(period, str(start), str(end), opportunities, signals,
                  round(1 - signals / opportunities, 4) if opportunities else 1.0, n,
                  round(wins / n, 4) if n else None, [round(ci[0], 4), round(ci[1], 4)] if n else None,
                  round(float(gp / gl), 3) if gl > 0 else None, round(float(pnl.mean()), 3) if n else None, ev_ci,
                  round(float(pnl.sum()), 2), round(dd, 2), sharpe,
                  round(float(np.mean(briers)), 4) if briers else None, by, {}, warnings)


def run(m15: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame, final: bool = False, refit_days: int = 5,
        min_edge: float = 0.10, holdout_frac: float = 0.2, registry: str | Path | None = None, seed: int = 7,
        execution=None) -> dict:
    """execution: None (fixed estimated costs) or a reliability.execution.ExecutionModel (realistic)."""
    rng = np.random.default_rng(seed)
    ds = P.build_path_dataset(m15, h1, h4)
    table = M.build_feature_table(m15, h1, h4)
    table = pd.merge_asof(table, _m30_dist(m15).rename("m30_dist").to_frame(), left_index=True, right_index=True)
    score = bias_score(table["h4_slope_ema50_atr"], table["h1_slope_ema50_atr"], table["m30_dist"],
                       table["ret_16"], table["vr4"])
    dirs = bias_direction(score)
    times = table.index
    cut = times[int(len(times) * (1 - holdout_frac))]
    lo_t, hi_t = (cut, times[-1]) if final else (times[int(len(times) * 0.35)], cut)
    period = "HOLDOUT (final)" if final else "DEVELOPMENT"
    sess = table["session"].to_numpy()
    weekday, hour = times.day_of_week, times.hour
    near_weekly_close = (weekday == 4) & (hour >= 17)
    # volatility regime per bar (as-of, from M15 features)
    f15 = frame_features(m15)
    vreg = {}
    eval_idx = [i for i, t in enumerate(times) if lo_t <= t < hi_t]
    refit_at, pm = None, None
    sig_idx, sig_dir, sig_p, base_idx, base_dir = [], [], [], [], []
    opportunities = 0
    for i in eval_idx:
        t = times[i]
        if sess[i] in ("CLOSED", "DAILY_BREAK") or near_weekly_close[i]:
            continue
        opportunities += 1
        d = int(dirs[i])
        if d == 0 or np.isnan(table["atr"].iloc[i]):
            continue
        if refit_at is None or t >= refit_at:
            pm = P.train_path_models(ds, t.to_pydatetime(), validate=False)
            refit_at = t + pd.Timedelta(days=refit_days)
        if i >= 300:
            r = classify(f15.iloc[: i + 1].tail(600))
            vreg[i] = volatility_regime(r, float(f15["ret_z"].iloc[i]) if f15["ret_z"].iloc[i] == f15["ret_z"].iloc[i] else 0.0)
        if vreg.get(i) == "EXCEPTIONAL":
            continue
        base_idx.append(i)
        base_dir.append(d)
        if pm is None or H not in pm.models:
            continue
        row = table.iloc[[i]].copy()
        for c in M.DIRECTIONAL:
            row[c] = row[c] * d
        row["dir"] = float(d)
        if row[M.FEATURES].isna().any(axis=None):
            continue
        p = pm.predict(row)[H]
        risk = 2.0 * table["atr"].iloc[i]
        ev = P.expected_net_return(float(p[0]), float(p[1]), risk, risk, EST_SPREAD + EST_SLIPPAGE)
        if ev >= min_edge:
            sig_idx.append(i)
            sig_dir.append(d)
            sig_p.append(p)
    trades = _simulate(m15, table, sig_idx, sig_dir, sig_p, min_edge, vreg, execution)
    rep = _metrics(trades, opportunities, len(sig_idx), period, lo_t, hi_t, rng)
    base_trades = _simulate(m15, table, base_idx, base_dir, [None] * len(base_idx), 0, vreg, execution)
    b = _metrics(base_trades, opportunities, len(base_idx), "baseline", lo_t, hi_t, rng)
    rep.baseline = {"rule": "نفس قاعدة الاتجاه بدون بوابة النموذج", "trades": b.trades, "win_rate": b.win_rate,
                    "ev_per_trade": b.ev_per_trade, "ev_ci95": b.ev_ci95, "profit_factor": b.profit_factor,
                    "max_drawdown": b.max_drawdown}
    if final and registry:
        reg = Path(registry)
        log = json.loads(reg.read_text()) if reg.exists() else []
        log.append({"ran_at": datetime.now(timezone.utc).isoformat(), "model": P.PATH_VERSION})
        reg.parent.mkdir(parents=True, exist_ok=True)
        reg.write_text(json.dumps(log, indent=1))
        if len(log) > 1:
            rep.warnings.append(f"فترة الاختبار النهائية استُخدمت {len(log)} مرات — خطر الإفراط في الملاءمة")
    out = asdict(rep)
    out["trades_sample"] = [asdict(t) for t in trades[:20]]
    out["costs"] = (execution.describe() if execution is not None else
                    {"spread": EST_SPREAD, "slippage": EST_SLIPPAGE, "note_ar": "تكاليف مُقدّرة وليست مقاسة"})
    out["trade_pnls"] = [t.pnl for t in trades]
    return out
