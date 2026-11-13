"""Triple-barrier labelling, leakage-safe dataset, baseline model and purged walk-forward validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import SESSION_CODES, frame_features, session_of
from .providers.base import TIMEFRAMES

MODEL_VERSION = "baseline-logit-0.1.0"
HORIZON_BARS = 16  # M15 bars -> 240 minutes
STOP_ATR = 2.0  # stop distance in M15 ATRs
TP_R = 1.0  # label target: TP1 at 1R
DIRECTIONAL = ["dist_ema20_atr", "slope_ema50_atr", "ret_4", "ret_16", "ret_z",
               "h1_slope_ema50_atr", "h1_dist_ema20_atr", "h4_slope_ema50_atr", "h4_dist_ema20_atr"]
SYMMETRIC = ["er20", "vr4", "vol_ratio", "range_z", "h1_er20", "h4_er20", "log_since_break"]
SESSIONS = ["ASIA", "LONDON", "LONDON_NY_OVERLAP", "NEW_YORK"]
FEATURES = DIRECTIONAL + SYMMETRIC + [f"sess_{s}" for s in SESSIONS] + ["dir"]


def _to_close_time(feats: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    f = feats.copy()
    f.index = f.index + pd.Timedelta(minutes=TIMEFRAMES[timeframe])
    return f


def build_feature_table(m15: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame) -> pd.DataFrame:
    """One row per M15 bar CLOSE time with higher-timeframe features known at that time (as-of join)."""
    f15 = _to_close_time(frame_features(m15), "M15")
    f15["entry"] = m15["close"].to_numpy()
    out = f15
    for name, df, tf in (("h1", h1, "H1"), ("h4", h4, "H4")):
        ff = _to_close_time(frame_features(df), tf)[["slope_ema50_atr", "dist_ema20_atr", "er20"]]
        ff.columns = [f"{name}_{c}" for c in ff.columns]
        out = pd.merge_asof(out.sort_index(), ff.sort_index(), left_index=True, right_index=True,
                            direction="backward")
    out["log_since_break"] = np.log1p(out["since_break"].clip(upper=2000))
    sess = [session_of(t - pd.Timedelta(minutes=1)) for t in out.index]
    for s in SESSIONS:
        out[f"sess_{s}"] = [1.0 if x == s else 0.0 for x in sess]
    out["session"] = sess
    return out


def barrier_labels(m15: pd.DataFrame, atr15: np.ndarray, direction: int,
                   horizon: int = HORIZON_BARS, stop_atr: float = STOP_ATR, tp_r: float = TP_R):
    """Binary view of barrier_outcomes: 1 if TP first, else 0 (SL first or timeout)."""
    out, res = barrier_outcomes(m15, atr15, direction, horizon, stop_atr, tp_r)
    lab = np.where(np.isnan(out), np.nan, (out == 1).astype(float))
    return lab, res


def barrier_outcomes(m15: pd.DataFrame, atr15: np.ndarray, direction: int,
                     horizon: int = HORIZON_BARS, stop_atr: float = STOP_ATR, tp_r: float = TP_R):
    """TP-before-SL within a WALL-CLOCK horizon of horizon*15 minutes (bars across the daily break or the
    weekend do not extend it). Same-bar touch of both => SL (conservative).
    Outcome codes: +1 TP first, -1 SL first, 0 neither within the horizon, NaN not yet knowable.
    Returns (outcome, resolve_minute) where resolve_minute is epoch minutes when the outcome is known."""
    hi, lo, cl = m15["high"].to_numpy(), m15["low"].to_numpy(), m15["close"].to_numpy()
    n = len(cl)
    t = (m15.index.tz_convert("UTC").as_unit("ns").asi8 // 60_000_000_000).astype(np.int64)
    window = horizon * 15
    risk = stop_atr * atr15
    label = np.full(n, np.nan)
    resolve = np.full(n, np.nan)
    pending = ~np.isnan(risk)
    # outcome is knowable only if some bar closes at/after decision+window within the data
    last_t = t[-1]
    pending &= (t + window) <= last_t
    label[pending] = 0.0
    # resolve holds the wall-clock MINUTE (bar close time) at which the outcome becomes known
    resolve[pending] = (t + 15 + window)[pending]  # close of the last bar inside the horizon
    open_ = pending.copy()
    for k in range(1, horizon + 1):
        j = np.minimum(np.arange(n) + k, n - 1)
        open_ &= (t[j] - t) <= window  # bar beyond the wall-clock horizon: stop scanning
        if direction > 0:
            sl_hit = lo[j] <= cl - risk
            tp_hit = hi[j] >= cl + tp_r * risk
        else:
            sl_hit = hi[j] >= cl + risk
            tp_hit = lo[j] <= cl - tp_r * risk
        sl_now = open_ & sl_hit
        tp_now = open_ & tp_hit & ~sl_hit
        label[tp_now] = 1.0
        label[sl_now] = -1.0
        resolve[sl_now | tp_now] = (t[j] + 15)[sl_now | tp_now]
        open_ &= ~(sl_now | tp_now)
    return label, resolve


def build_dataset(m15: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame) -> pd.DataFrame:
    table = build_feature_table(m15, h1, h4)
    close_times = table.index
    rows = []
    for d in (1, -1):
        lab, res = barrier_labels(m15, table["atr"].to_numpy(), d)
        part = table.copy()
        for c in DIRECTIONAL:
            part[c] = part[c] * d
        part["dir"] = float(d)
        part["label"] = lab
        part["label_known_at"] = pd.to_datetime(res, unit="m", utc=True)
        rows.append(part)
    ds = pd.concat(rows).dropna(subset=FEATURES + ["label"])
    ds["decision_time"] = ds.index
    return ds.sort_values(["decision_time", "dir"])


def make_model():
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=500))


@dataclass
class TrainedModel:
    model: object
    trained_until: datetime
    n_samples: int
    base_rate: float
    version: str = MODEL_VERSION

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(x[FEATURES].to_numpy())[:, 1]


def train_as_of(ds: pd.DataFrame, as_of: datetime, min_samples: int = 2000) -> TrainedModel | None:
    """Train only on samples whose label was already KNOWN at as_of (no look-ahead)."""
    known = ds[ds["label_known_at"] <= pd.Timestamp(as_of)]
    if len(known) < min_samples or known["label"].nunique() < 2:
        return None
    m = make_model().fit(known[FEATURES].to_numpy(), known["label"].to_numpy())
    return TrainedModel(model=m, trained_until=as_of, n_samples=len(known), base_rate=float(known["label"].mean()))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)


@dataclass
class WalkForwardReport:
    folds: int
    n_oos: int
    base_rate: float
    brier_model: float
    brier_base: float
    calibration: list = field(default_factory=list)
    selective: list = field(default_factory=list)
    development_end: str = ""
    holdout_start: str = ""
    notes: list = field(default_factory=list)


def purged_walk_forward(ds: pd.DataFrame, n_folds: int = 5, holdout_frac: float = 0.2,
                        embargo: pd.Timedelta = pd.Timedelta(minutes=15 * HORIZON_BARS)) -> WalkForwardReport:
    times = ds["decision_time"].sort_values().unique()
    cut = times[int(len(times) * (1 - holdout_frac))]
    dev = ds[ds["decision_time"] < cut]  # final holdout untouched here
    dtimes = dev["decision_time"].sort_values().unique()
    edges = np.linspace(len(dtimes) * 0.4, len(dtimes), n_folds + 1).astype(int)
    preds, ys, bases = [], [], []
    for a, b in zip(edges[:-1], edges[1:]):
        t0, t1 = dtimes[a], dtimes[min(b, len(dtimes) - 1)]
        train = dev[(dev["label_known_at"] < t0 - embargo)]  # purge: label must be known before test start
        test = dev[(dev["decision_time"] >= t0) & (dev["decision_time"] < t1)]
        if len(train) < 1000 or test.empty or train["label"].nunique() < 2:
            continue
        m = make_model().fit(train[FEATURES].to_numpy(), train["label"].to_numpy())
        preds.append(m.predict_proba(test[FEATURES].to_numpy())[:, 1])
        ys.append(test["label"].to_numpy())
        bases.append(np.full(len(test), float(train["label"].mean())))  # climatology known at train time
    p = np.concatenate(preds) if preds else np.array([])
    y = np.concatenate(ys) if ys else np.array([])
    bvec = np.concatenate(bases) if bases else np.array([])
    base = float(y.mean()) if len(y) else float("nan")
    rep = WalkForwardReport(folds=len(preds), n_oos=len(y), base_rate=base,
                            brier_model=float(np.mean((p - y) ** 2)) if len(y) else float("nan"),
                            brier_base=float(np.mean((bvec - y) ** 2)) if len(y) else float("nan"),
                            development_end=str(cut), holdout_start=str(cut))
    if len(y):
        bins = np.linspace(0, 1, 11)
        idx = np.clip(np.digitize(p, bins) - 1, 0, 9)
        for b in range(10):
            mask = idx == b
            if mask.sum() >= 20:
                rep.calibration.append({"bin": f"{bins[b]:.1f}-{bins[b+1]:.1f}", "n": int(mask.sum()),
                                        "mean_pred": round(float(p[mask].mean()), 4),
                                        "observed": round(float(y[mask].mean()), 4)})
        for thr in (0.5, 0.55, 0.6, 0.65, 0.7):
            mask = p >= thr
            k, n = int(y[mask].sum()), int(mask.sum())
            lo, hi = wilson(k, n)
            rep.selective.append({"threshold": thr, "signals": n, "hit_rate": round(k / n, 4) if n else None,
                                  "ci95": [round(lo, 4), round(hi, 4)] if n else None,
                                  "low_sample_warning": n < 300})
    return rep
