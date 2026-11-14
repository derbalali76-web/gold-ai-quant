"""Trade-plan engine (v1): compare several entry / target / stop plans and pick the best by expected return after costs.

For every decision day t and direction d, each candidate plan c = (entry kind, target multiple, stop multiple) is
simulated on the bars AFTER t (no look-ahead): a LIMIT entry must first fill inside its window, then target and stop
are checked bar by bar (same bar touching both = stop, conservative), otherwise the plan times out at the horizon.
A multinomial model per (d, c) learns P(target first), P(stop first), P(timeout) and, for LIMIT, P(fill), from
features known at t's close. Expected net return of a plan = what those probabilities imply minus round-trip cost.

Walk-forward with purge + embargo: a training sample is used only once its outcome was known before the test block
started. Three things are measured separately, never mixed:
  * direction accuracy  — sign of the horizon return vs the majority-class baseline
  * trade success       — share of taken plans that hit the target before the stop
  * profitability       — mean net return per trade after costs, its bootstrap CI, drawdown
A horizon qualifies only if profitability holds out of sample (CI > 0, both halves, final holdout) AND the
probabilities are calibrated (Brier better than climatology, small reliability gap). Otherwise: no recommendation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import outlook as OL

PLANNER_VERSION = "planner-daily-1.0.0"
COST = OL.ROUND_TRIP_COST  # fraction of price per round trip (spread + slippage); per asset via cost_of()
ASSET_COST = {"XAUUSD": OL.ROUND_TRIP_COST,
              # crypto spot: 0.10 % taker fee each side + spread/slippage (conservative, no fee discounts)
              "BTCUSDT": 0.0022, "ETHUSDT": 0.0022, "SOLUSDT": 0.0025,
              # USD-M perpetuals: 0.05 % taker each side + slippage (no maker assumption: fills are not guaranteed)
              "BTCUSDT_PERP": 0.0012, "ETHUSDT_PERP": 0.0012, "SOLUSDT_PERP": 0.0014}
FLOW = ["vol_z", "taker20", "taker_imb", "funding", "funding_chg"]  # crypto only (real volume, perp funding)
METRICS = ["oi_chg4", "oi_chg24", "top_ls", "taker_ls"]  # crypto perps: open interest, top-trader & taker ratios


class cost_of:
    """Context manager: simulate / expected use this asset's round-trip cost."""
    def __init__(self, asset: Optional[str]):
        self.c = ASSET_COST.get(asset or "XAUUSD", OL.ROUND_TRIP_COST)

    def __enter__(self):
        global COST
        self.old, COST = COST, self.c

    def __exit__(self, *a):
        global COST
        COST = self.old
HORIZONS = {"WEEK": 5, "MONTH": 21, "HOURS": 8}  # in bars: daily bars for WEEK / MONTH, H1 bars for HOURS
DAILY_HZ = ("WEEK", "MONTH")
GEOMETRIES = {  # (target, stop) in ATR(20) units of the horizon's own bars
    "WEEK": [(1.0, 1.0), (1.5, 1.0), (2.0, 1.5), (2.5, 1.5)],
    "MONTH": [(2.0, 1.5), (3.0, 2.0), (4.0, 2.5), (5.0, 3.0)],
    "HOURS": [(1.0, 1.0), (1.5, 1.0), (2.0, 1.0), (2.0, 1.5)],
}
LIMIT_PULLBACK = 0.5  # LIMIT entry 0.5 ATR better than the close
FILL_WINDOW = {"WEEK": 2, "MONTH": 5, "HOURS": 2}  # bars allowed for a LIMIT entry to fill
MIN_TRAIN = 1000
TEST_BLOCK = 250
TRAIN_BARS = {"HOURS": 3000}  # ~6 months of H1 bars before the first test block
BLOCK_BARS = {"HOURS": 500}  # refit about monthly
INTRADAY = ["hsin", "hcos"]
CROSS_SYMBOLS = ("DOLLARIDXUSD", "USTBONDTRUSD", "USA500IDXUSD", "EURUSD", "USDJPY", "XAGUSD")


def cross_cols(symbols) -> list:
    return [f"{s_}_r{k}" for s_ in symbols for k in (1, 4, 8)]


def cross_features(index: pd.DatetimeIndex, aux: dict) -> pd.DataFrame:
    """Log returns of related markets over the last 1 / 4 / 8 H1 bars, aligned on the SAME bar (both known at the
    bar's close). Missing hours stay NaN (no forward fill across gaps)."""
    out = pd.DataFrame(index=index)
    for s_, df in aux.items():
        lc = np.log(df["close"].astype(float))
        lc = lc[~lc.index.duplicated()].reindex(index)
        for k in (1, 4, 8):
            out[f"{s_}_r{k}"] = lc - lc.shift(k)
    return out  # hour of day (unsigned): London / New York sessions behave differently
HOLDOUT_FRAC = 0.2
MIN_EDGE = 0.0005  # require at least +0.05 % expected net return per trade


@dataclass(frozen=True)
class Candidate:
    direction: int
    entry: str  # MARKET | LIMIT
    tp: float
    sl: float

    @property
    def key(self) -> str:
        return f"{'L' if self.direction > 0 else 'S'}_{self.entry}_{self.tp}_{self.sl}"


def candidates(horizon: str) -> list[Candidate]:
    return [Candidate(d, e, tp, sl) for d in (1, -1) for e in ("MARKET", "LIMIT") for tp, sl in GEOMETRIES[horizon]]


# ------------------------------------------------------------------ features (row t uses bars up to t only)
FEATURES = ["dist20", "dist50", "dist200", "mom63", "mom126", "mom252", "ret5", "ret20", "rsi", "rangepos", "atr_pct"]
# macro (FRED, point in time): real-yield and dollar changes act on gold with a sign -> flipped for shorts;
# expected gold volatility (GVZ) is unsigned
MACRO = ["ry5", "ry20", "usd5", "usd20", "gvz_z", "gvz5"]
MACRO_SERIES = ("DFII10", "DTWEXBGS", "GVZCLS")
SIGNED = ["dist20", "dist50", "dist200", "mom63", "mom126", "mom252", "ret5", "ret20", "rsi", "rangepos",
          "ry5", "ry20", "usd5", "usd20", "taker20", "taker_imb", "funding", "funding_chg", "top_ls", "taker_ls"]


def macro_features(index: pd.DatetimeIndex, macro: dict) -> pd.DataFrame:
    """Macro columns for daily bars `index` (bar OPEN times). A value is used only once PUBLISHED before the bar
    closed (published_at <= open + 1 day): FRED rows carry a conservative publication lag (sources/fred.py)."""
    out = pd.DataFrame(index=index)
    close_t = pd.DataFrame({"t": np.asarray(index + pd.Timedelta(days=1))})

    def series(name, fn):
        df = macro.get(name)
        if df is None or len(df) == 0:
            return None
        df = df.copy()
        df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"]).sort_values("published_at").reset_index(drop=True)
        vals = fn(df["value"])
        m = pd.merge_asof(close_t, pd.DataFrame({"t": np.asarray(df["published_at"]), **vals}),
                          on="t", direction="backward")
        m.index = index
        return m

    ry = series("DFII10", lambda v: {"ry5": v.diff(5), "ry20": v.diff(20)})
    usd = series("DTWEXBGS", lambda v: {"usd5": np.log(v).diff(5), "usd20": np.log(v).diff(20)})
    gvz = series("GVZCLS", lambda v: {"gvz_z": (v - v.rolling(252).mean()) / v.rolling(252).std(),
                                      "gvz5": np.log(v).diff(5)})
    for m, cols in ((ry, ("ry5", "ry20")), (usd, ("usd5", "usd20")), (gvz, ("gvz_z", "gvz5"))):
        for c in cols:
            out[c] = m[c] if m is not None else np.nan
    return out


def flow_features(d: pd.DataFrame, funding: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Crypto: real-volume z-score, taker-buy share (who initiated trades), and the perpetual funding rate known
    at the bar's close (asof on the funding time)."""
    out = pd.DataFrame(index=d.index)
    if "volume" in d.columns:
        lv = np.log(d["volume"].astype(float).clip(lower=1e-12))
        out["vol_z"] = (lv - lv.rolling(48).mean()) / lv.rolling(48).std()
    if "taker_buy_volume" in d.columns and "volume" in d.columns:
        share = (d["taker_buy_volume"] / d["volume"].replace(0, np.nan)) - 0.5
        out["taker20"] = share.rolling(20).mean()
        out["taker_imb"] = share.rolling(4).mean()
    if funding is not None and len(funding):
        f = funding["funding"].astype(float).sort_index()
        close_t = pd.DataFrame({"t": np.asarray(d.index + (d.index.to_series().diff().median()
                                                           if len(d) > 2 else pd.Timedelta(hours=1)))})
        m = pd.merge_asof(close_t, pd.DataFrame({"t": np.asarray(f.index), "funding": f.to_numpy(),
                                                 "funding_chg": f.diff(3).to_numpy()}), on="t", direction="backward")
        out["funding"], out["funding_chg"] = m["funding"].to_numpy(), m["funding_chg"].to_numpy()
    if "oi" in d.columns:
        loi = np.log(d["oi"].astype(float).where(d["oi"] > 0))
        out["oi_chg4"], out["oi_chg24"] = loi - loi.shift(4), loi - loi.shift(24)
    if "top_ls_ratio" in d.columns:
        out["top_ls"] = np.log(d["top_ls_ratio"].astype(float).where(d["top_ls_ratio"] > 0))
    if "taker_ls_ratio" in d.columns:
        out["taker_ls"] = np.log(d["taker_ls_ratio"].astype(float).where(d["taker_ls_ratio"] > 0)).rolling(4).mean()
    for c in FLOW + METRICS:
        if c not in out.columns:
            out[c] = np.nan
    return out


def features(d: pd.DataFrame, macro: Optional[dict] = None, aux: Optional[dict] = None,
             funding: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    f = OL.daily_features(d)
    a = f["atr20"]
    out = pd.DataFrame(index=d.index)
    for k in (20, 50, 200):
        out[f"dist{k}"] = (f["close"] - f[f"sma{k}"]) / a
    for k in (63, 126, 252):
        out[f"mom{k}"] = f[f"mom{k}"]
    lc = np.log(d["close"])
    out["ret5"] = lc - lc.shift(5)
    out["ret20"] = lc - lc.shift(20)
    out["rsi"] = (f["rsi14"] - 50) / 50
    hi, lo = d["high"].rolling(20).max(), d["low"].rolling(20).min()
    out["rangepos"] = (d["close"] - lo) / (hi - lo) - 0.5
    out["atr_pct"] = a / d["close"]
    out["atr"] = a
    if macro is not None:
        out = out.join(macro_features(d.index, macro))
    if aux:
        out = out.join(cross_features(d.index, aux))
    if "volume" in d.columns and "taker_buy_volume" in d.columns:
        out = out.join(flow_features(d, funding))
    hr = (d.index.hour + 1) % 24  # hour at the bar's close
    out["hsin"], out["hcos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    return out


# Pre-registered market regimes (fixed BEFORE testing, few on purpose: every extra variant raises the chance of a
# lucky result). A regime model only trades — and only learns — inside its regime.
REGIMES = ("TREND", "RANGE", "HIGH_VOL")


def regime_mask(feats: pd.DataFrame, regime: Optional[str]) -> np.ndarray:
    if not regime:
        return np.ones(len(feats), bool)
    d50, m63, ap = feats["dist50"], feats["mom63"], feats["atr_pct"]
    if regime == "TREND":
        m = (d50.abs() >= 1.0) & (np.sign(d50) == np.sign(m63))
    elif regime == "RANGE":
        m = d50.abs() < 0.5
    elif regime == "HIGH_VOL":
        m = ap > ap.rolling(250, min_periods=100).median().shift(1) * 1.3
    else:
        raise ValueError(regime)
    return m.fillna(False).to_numpy()


def intraday_allowed(index: pd.DatetimeIndex, horizon_bars: int) -> np.ndarray:
    """H1 decision times that can be held for the whole horizon inside one trading week: not in the weekly close
    or the daily break, and the horizon must end before Friday 21:00 UTC (no weekend gap inside a trade)."""
    close_t = index + pd.Timedelta(hours=1)
    end_t = close_t + pd.Timedelta(hours=horizon_bars + 2)

    def closed(t):
        dow, h = t.day_of_week, t.hour
        return (dow == 5) | ((dow == 4) & (h >= 21)) | ((dow == 6) & (h < 22))
    bad = closed(close_t) | (close_t.hour == 21) | closed(end_t) | ((close_t.day_of_week == 4) & (end_t.day_of_week != 4))
    return ~np.asarray(bad)


def signed(x: np.ndarray, direction: int, cols: Optional[list] = None) -> np.ndarray:
    cols = cols or FEATURES
    y = x.copy()
    idx = [i for i, c in enumerate(cols) if c in SIGNED or c.rsplit("_", 1)[-1] in ("r1", "r4", "r8")]
    y[:, idx] *= direction
    return y


# ------------------------------------------------------------------ simulation (bars strictly after t)
def simulate(o, h, l, c, atr, i: int, cand: Candidate, horizon_bars: int, fill_window: int) -> tuple:
    """Returns (outcome, net_return, bars_held). outcome: 1 target, -1 stop, 0 timeout, nan unfilled / unresolvable."""
    n = len(c)
    a = atr[i]
    if not np.isfinite(a) or a <= 0:
        return np.nan, np.nan, np.nan
    d = cand.direction
    entry = c[i] - d * LIMIT_PULLBACK * a if cand.entry == "LIMIT" else c[i]
    start = i + 1
    if cand.entry == "LIMIT":
        fill = None
        for j in range(start, min(i + 1 + fill_window, n)):
            if (l[j] <= entry if d > 0 else h[j] >= entry):
                fill = j
                break
        if fill is None:
            return (np.nan, 0.0, fill_window) if i + fill_window < n else (np.nan, np.nan, np.nan)
        start = fill
    tp, sl = entry + d * cand.tp * a, entry - d * cand.sl * a
    end = i + horizon_bars
    if end >= n:
        return np.nan, np.nan, np.nan
    for j in range(start, end + 1):
        hit_sl = l[j] <= sl if d > 0 else h[j] >= sl
        hit_tp = h[j] >= tp if d > 0 else l[j] <= tp
        if hit_sl:
            return -1.0, d * (sl - entry) / entry - COST, j - i
        if hit_tp:
            return 1.0, d * (tp - entry) / entry - COST, j - i
    return 0.0, d * (c[end] - entry) / entry - COST, end - i


def label_all(d: pd.DataFrame, horizon: str) -> dict:
    o, h, l, c = (d[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    atr = features(d)["atr"].to_numpy()
    H, F = HORIZONS[horizon], FILL_WINDOW[horizon]
    out = {}
    for cand in candidates(horizon):
        res = np.array([simulate(o, h, l, c, atr, i, cand, H, F) for i in range(len(c))], dtype=float)
        out[cand.key] = res  # columns: outcome, net_return, bars_held
    return out


# ------------------------------------------------------------------ models
def _fit_multi(x, y):
    m = make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=2000))
    m.fit(x, y)
    return m


def _proba(m, x, classes):
    p = m.predict_proba(x)
    cls = list(m.classes_)
    return np.stack([p[:, cls.index(k)] if k in cls else np.zeros(len(x)) for k in classes], axis=1)


@dataclass
class CandModel:
    cand: Candidate
    outcome: object = None  # 3-class model on filled samples
    fill: object = None  # binary model (LIMIT only)
    mean_timeout: float = 0.0
    tp_ret: float = 0.0  # mean net return when target / stop is hit, in ATR-relative terms (per unit atr_pct)
    sl_ret: float = 0.0
    base_tp: float = 0.0
    median_days_tp: Optional[float] = None
    cols: Optional[list] = None


def fit_models(X: np.ndarray, labels: dict, train_idx: np.ndarray, horizon: str, cols: Optional[list] = None) -> dict:
    models = {}
    for cand in candidates(horizon):
        lab = labels[cand.key][train_idx]
        xs = signed(X[train_idx], cand.direction, cols)
        ok = np.isfinite(xs).all(axis=1)
        filled = ok & np.isfinite(lab[:, 0])
        cm = CandModel(cand, cols=cols)
        if filled.sum() < 100 or len(np.unique(lab[filled, 0])) < 2:
            models[cand.key] = cm
            continue
        cm.outcome = _fit_multi(xs[filled], lab[filled, 0].astype(int))
        to = filled & (lab[:, 0] == 0)
        cm.mean_timeout = float(np.mean(lab[to, 1])) if to.any() else 0.0
        cm.base_tp = float(np.mean(lab[filled, 0] == 1))
        tpd = lab[filled & (lab[:, 0] == 1), 2]
        cm.median_days_tp = float(np.median(tpd)) if len(tpd) else None
        if cand.entry == "LIMIT":
            resolved = ok & np.isfinite(lab[:, 1])
            yfill = np.isfinite(lab[resolved, 0]).astype(int)
            if len(np.unique(yfill)) == 2:
                cm.fill = _fit_multi(xs[resolved], yfill)
        models[cand.key] = cm
    return models


def expected(cm: CandModel, x_row: np.ndarray, atr_pct: float) -> tuple:
    """(EV after costs, p_tp, p_sl, p_to, p_fill) for one candidate at one decision time."""
    if cm.outcome is None or not np.isfinite(x_row).all():
        return -np.inf, None, None, None, None
    xs = signed(x_row[None, :], cm.cand.direction, getattr(cm, "cols", None))
    p = _proba(cm.outcome, xs, [1, -1, 0])[0]
    pf = 1.0
    if cm.cand.entry == "LIMIT":
        pf = float(_proba(cm.fill, xs, [1])[0, 0]) if cm.fill is not None else 0.0
    gain = cm.cand.tp * atr_pct - COST
    loss = -cm.cand.sl * atr_pct - COST
    ev = pf * (p[0] * gain + p[1] * loss + p[2] * cm.mean_timeout)
    return float(ev), float(p[0]), float(p[1]), float(p[2]), pf


# ------------------------------------------------------------------ walk-forward evaluation
@dataclass
class PlannerReport:
    horizon: str
    version: str = PLANNER_VERSION
    period: str = ""
    decision_days: int = 0
    direction_accuracy: Optional[float] = None
    direction_baseline: Optional[float] = None
    trades: int = 0
    not_filled: int = 0
    tp_first_rate: Optional[float] = None
    timeout_rate: Optional[float] = None
    avg_win_pct: Optional[float] = None
    avg_loss_pct: Optional[float] = None
    expectancy_pct: Optional[float] = None
    expectancy_ci95: Optional[list] = None
    expectancy_halves: list = field(default_factory=list)
    holdout_expectancy_pct: Optional[float] = None
    holdout_trades: int = 0
    max_drawdown_pct: Optional[float] = None
    profit_factor: Optional[float] = None
    median_days_to_target: Optional[float] = None
    brier_tp: Optional[float] = None
    brier_climatology: Optional[float] = None
    reliability_gap: Optional[float] = None
    plans_used: dict = field(default_factory=dict)
    baseline_plan: Optional[str] = None
    baseline_expectancy_pct: Optional[float] = None  # same plan taken every time (no model), same period, same rules
    baseline_trades: int = 0
    edge_over_baseline_ci95: Optional[list] = None
    qualified: bool = False  # the plan selection is profitable out of sample AND beats the no-model baseline
    probabilities_calibrated: bool = False  # only then may probabilities be shown as numbers
    reason: str = ""
    checks: dict = field(default_factory=dict)
    features: list = field(default_factory=lambda: list(FEATURES))
    regime: Optional[str] = None


def _purged_train(n_upto: int, H: int, F: int) -> np.ndarray:
    """Samples whose outcome was known strictly before index n_upto (purge) with an extra embargo of H bars."""
    last = n_upto - (H + F) - H
    return np.arange(0, max(last, 0))


def walk_forward(d: pd.DataFrame, horizon: str, seed: int = 7, macro: Optional[dict] = None,
                 cols: Optional[list] = None, since=None, aux: Optional[dict] = None, asset: str = "XAUUSD",
                 funding: Optional[pd.DataFrame] = None, min_train: Optional[int] = None,
                 test_block: Optional[int] = None, regime: Optional[str] = None) -> PlannerReport:
    """min_train / test_block override the horizon defaults (long H1 histories refit less often).
    regime: one of REGIMES — the model learns and trades only inside that regime."""
    with cost_of(asset):
        return _walk_forward(d, horizon, seed, macro, cols, since, aux, asset, funding, min_train, test_block, regime)


def _walk_forward(d, horizon, seed, macro, cols, since, aux, asset, funding, min_train=None,
                  test_block=None, regime=None) -> PlannerReport:
    """cols: feature columns (default FEATURES; FEATURES + MACRO needs `macro`). since: evaluate only from this
    date (features and labels still use the earlier bars), so two feature sets can be compared on one period."""
    d = d.dropna(subset=["open", "high", "low", "close"])
    cols = cols or FEATURES
    H, F = HORIZONS[horizon], FILL_WINDOW[horizon]
    feats = features(d, macro if any(c in MACRO for c in cols) else None, aux, funding)
    labels = label_all(d, horizon)
    if since is not None:
        ts_ = pd.Timestamp(since)
        if d.index.tz is not None and ts_.tzinfo is None:
            ts_ = ts_.tz_localize("UTC")
        keep = d.index >= ts_
        d, feats = d[keep], feats[keep]
        labels = {k: v[keep] for k, v in labels.items()}
    X = feats[cols].to_numpy(dtype=float)
    if regime:
        X[~regime_mask(feats, regime)] = np.nan
    if horizon == "HOURS" and "USDT" not in asset:
        # metals: no decision (and no training sample) that would carry a trade over the weekend; crypto is 24/7
        X[~intraday_allowed(d.index, HORIZONS[horizon])] = np.nan
    atr_pct = feats["atr_pct"].to_numpy(dtype=float)
    c = d["close"].to_numpy(dtype=float)
    n = len(c)
    rep = PlannerReport(horizon, features=list(cols), regime=regime)
    MIN_TRAIN = min_train or TRAIN_BARS.get(horizon, globals()["MIN_TRAIN"])
    TEST_BLOCK = test_block or BLOCK_BARS.get(horizon, globals()["TEST_BLOCK"])
    if n < MIN_TRAIN + TEST_BLOCK:
        rep.reason = f"insufficient daily history ({n} bars)"
        return rep
    hold_start = int(n * (1 - HOLDOUT_FRAC))
    trades, dir_hits, dir_n, cal = [], 0, 0, []
    dir_up = 0
    i = MIN_TRAIN
    models, model_block = None, -1
    next_free = MIN_TRAIN
    while i < n - H:
        block = (i - MIN_TRAIN) // TEST_BLOCK
        if block != model_block:
            tr = _purged_train(MIN_TRAIN + block * TEST_BLOCK, H, F)
            models = fit_models(X, labels, tr, horizon, cols)
            # direction model (sign of the H-day return)
            fwd = np.full(n, np.nan)
            fwd[:-H] = np.log(c[H:] / c[:-H])
            ok = np.isfinite(X[tr]).all(axis=1) & np.isfinite(fwd[tr])
            dir_model = _fit_multi(X[tr][ok], (fwd[tr][ok] > 0).astype(int)) if ok.sum() > 100 else None
            model_block = block
        if np.isfinite(X[i]).all() and dir_model is not None:
            up = _proba(dir_model, X[i][None, :], [1])[0, 0] >= 0.5
            real = np.log(c[i + H] / c[i]) > 0
            dir_hits += int(up == real)
            dir_up += int(real)
            dir_n += 1
        if i >= next_free and np.isfinite(atr_pct[i]):
            best, best_key = (-np.inf,), None
            for k, cm in models.items():
                e = expected(cm, X[i], atr_pct[i])
                if e[0] > best[0]:
                    best, best_key = e, k
            if best_key is not None and best[0] > MIN_EDGE:
                out, ret, held = labels[best_key][i]
                if np.isfinite(ret):
                    filled = np.isfinite(out)
                    trades.append({"i": i, "key": best_key, "filled": bool(filled), "outcome": out, "ret": ret,
                                   "held": held, "p_tp": best[1], "base": models[best_key].base_tp,
                                   "hold": i >= hold_start})
                    next_free = i + int(held if np.isfinite(held) else F) + 1
        i += 1
    rep.period = f"{d.index[MIN_TRAIN].date()} → {d.index[min(i, n - 1)].date()}"
    rep.decision_days = dir_n
    if dir_n:
        rep.direction_accuracy = round(dir_hits / dir_n, 4)
        rep.direction_baseline = round(max(dir_up, dir_n - dir_up) / dir_n, 4)
    filled = [t for t in trades if t["filled"]]
    rep.not_filled = len(trades) - len(filled)
    rep.trades = len(filled)
    if not filled:
        rep.reason = "no plan reached the minimum expected edge"
        return rep
    r = np.array([t["ret"] for t in filled]) * 100
    oc = np.array([t["outcome"] for t in filled])
    rep.tp_first_rate = round(float(np.mean(oc == 1)), 4)
    rep.timeout_rate = round(float(np.mean(oc == 0)), 4)
    rep.avg_win_pct = round(float(r[r > 0].mean()), 3) if (r > 0).any() else None
    rep.avg_loss_pct = round(float(r[r <= 0].mean()), 3) if (r <= 0).any() else None
    rep.expectancy_pct = round(float(r.mean()), 3)
    rng = np.random.default_rng(seed)
    boots = [rng.choice(r, len(r), replace=True).mean() for _ in range(2000)]
    rep.expectancy_ci95 = [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)]
    half = len(r) // 2
    rep.expectancy_halves = [round(float(r[:half].mean()), 3) if half else None,
                             round(float(r[half:].mean()), 3) if len(r) - half else None]
    hr = np.array([t["ret"] for t in filled if t["hold"]]) * 100
    rep.holdout_trades = int(len(hr))
    rep.holdout_expectancy_pct = round(float(hr.mean()), 3) if len(hr) else None
    eq = np.cumsum(r)
    rep.max_drawdown_pct = round(float(np.max(np.maximum.accumulate(eq) - eq)), 3)
    gp, gl = r[r > 0].sum(), -r[r < 0].sum()
    rep.profit_factor = round(float(gp / gl), 3) if gl > 0 else None
    tp_days = [t["held"] for t in filled if t["outcome"] == 1]
    rep.median_days_to_target = float(np.median(tp_days)) if tp_days else None
    p = np.array([t["p_tp"] for t in filled])
    y = (oc == 1).astype(float)
    base = np.array([t["base"] for t in filled])
    rep.brier_tp = round(float(np.mean((p - y) ** 2)), 4)
    rep.brier_climatology = round(float(np.mean((base - y) ** 2)), 4)
    gaps = []
    for lo in np.arange(0, 1, 0.2):
        m = (p >= lo) & (p < lo + 0.2)
        if m.sum() >= 15:
            gaps.append(abs(float(p[m].mean() - y[m].mean())))
    rep.reliability_gap = round(max(gaps), 4) if gaps else None
    rep.plans_used = pd.Series([t["key"] for t in filled]).value_counts().head(6).to_dict()
    # baseline: the model's most used plan, taken at every opportunity without the model (non-overlapping, same span)
    top = max(rep.plans_used, key=rep.plans_used.get)
    rep.baseline_plan = top
    b, j = [], MIN_TRAIN
    while j < n - H:
        out_, ret_, held_ = labels[top][j]
        if not np.isfinite(ret_) or ((horizon == "HOURS" or regime) and not np.isfinite(X[j]).all()):
            j += 1  # same eligible decision times as the model (no weekend-crossing trade)
            continue
        if np.isfinite(out_):
            b.append(ret_ * 100)
        j += int(held_ if np.isfinite(held_) else F) + 1
    rep.baseline_trades = len(b)
    rep.baseline_expectancy_pct = round(float(np.mean(b)), 3) if b else None
    diff_lo = None
    if b:
        bb = np.array(b)
        diffs = [rng.choice(r, len(r)).mean() - rng.choice(bb, len(bb)).mean() for _ in range(2000)]
        diff_lo = float(np.percentile(diffs, 2.5))
        rep.edge_over_baseline_ci95 = [round(diff_lo, 3), round(float(np.percentile(diffs, 97.5)), 3)]
    checks = {
        "enough trades (>=30)": rep.trades >= 30,
        "expectancy CI above zero": rep.expectancy_ci95[0] > 0,
        "both halves positive": all(x is not None and x > 0 for x in rep.expectancy_halves),
        "final holdout positive": rep.holdout_expectancy_pct is not None and rep.holdout_expectancy_pct > 0,
        "beats the no-model baseline (CI)": diff_lo is not None and diff_lo > 0,
    }
    cal = {
        "Brier better than climatology": rep.brier_tp <= rep.brier_climatology,
        "reliability gap <= 0.10": rep.reliability_gap is not None and rep.reliability_gap <= 0.10,
    }
    rep.checks = {**checks, **cal}
    rep.qualified = all(checks.values())
    rep.probabilities_calibrated = rep.qualified and all(cal.values())
    failed = [k for k, v in checks.items() if not v]
    rep.reason = ("qualified" + ("" if rep.probabilities_calibrated else " (probabilities not calibrated: hidden)")
                  if rep.qualified else "failed: " + "; ".join(failed))
    return rep


# ------------------------------------------------------------------ production model (fitted on all resolved data)
@dataclass
class PlannerModel:
    horizon: str
    models: dict
    report: dict
    trained_until: str
    version: str = PLANNER_VERSION
    cols: Optional[list] = None

    @property
    def qualified(self) -> bool:
        return bool(self.report.get("qualified"))

    def best_plan(self, d: pd.DataFrame, macro: Optional[dict] = None) -> Optional[dict]:
        """Best plan for the last CLOSED daily bar of d, or None when no candidate clears the edge (or when the
        model needs macro data that is not available: never a plan from incomplete inputs)."""
        cols = getattr(self, "cols", None) or FEATURES
        needs_macro = any(c in MACRO for c in cols)
        if needs_macro and not macro:
            return None
        feats = features(d, macro if needs_macro else None)
        reg = (self.report or {}).get("regime")
        if reg and not regime_mask(feats, reg)[-1]:
            return None  # a regime model is silent outside its regime
        x = feats[cols].to_numpy(dtype=float)[-1]
        a, ap, close = float(feats["atr"].iloc[-1]), float(feats["atr_pct"].iloc[-1]), float(d["close"].iloc[-1])
        best, cand = (-np.inf,), None
        for cm in self.models.values():
            e = expected(cm, x, ap)
            if e[0] > best[0]:
                best, cand = e, cm
        if cand is None or best[0] <= MIN_EDGE:
            return None
        k = cand.cand
        entry = close - k.direction * LIMIT_PULLBACK * a if k.entry == "LIMIT" else close
        return {"direction": k.direction, "entry_kind": k.entry, "entry": round(entry, 2),
                "target": round(entry + k.direction * k.tp * a, 2), "stop": round(entry - k.direction * k.sl * a, 2),
                "ev_pct": round(best[0] * 100, 3), "p_target": round(best[1], 4), "p_stop": round(best[2], 4),
                "p_timeout": round(best[3], 4), "p_fill": round(best[4], 4),
                "median_days_to_target": cand.median_days_tp, "horizon_days": HORIZONS[self.horizon],
                "fill_days": FILL_WINDOW[self.horizon] if k.entry == "LIMIT" else 0}


def train_production(d: pd.DataFrame, horizon: str, report: PlannerReport, macro: Optional[dict] = None) -> PlannerModel:
    d = d.dropna(subset=["open", "high", "low", "close"])
    cols = list(report.features or FEATURES)
    feats = features(d, macro if any(c in MACRO for c in cols) else None)
    X = feats[cols].to_numpy(dtype=float)
    if report.regime:
        X[~regime_mask(feats, report.regime)] = np.nan
    labels = label_all(d, horizon)
    tr = _purged_train(len(d), HORIZONS[horizon], FILL_WINDOW[horizon])
    return PlannerModel(horizon, fit_models(X, labels, tr, horizon, cols), asdict(report), str(d.index[-1].date()),
                        cols=cols)
