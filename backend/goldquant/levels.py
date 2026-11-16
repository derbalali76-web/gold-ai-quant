"""Support & Resistance Strength Engine.

Levels
  Swing pivots on M15 / H1 / H4 (a pivot is only KNOWN k bars after it formed), clustered into price zones
  (gap <= 0.35 x ATR(H1)) as of the decision time. Supports lie below the price, resistances above,
  both ordered by DISTANCE to the price (S1/R1 = nearest).

Strength features (all computed from bars strictly before the evaluation time)
  1 tests          number of distinct approaches to the zone
  2 rejection      mean move away from the zone after a test, in ATR
  3 recency        exp(-days since last test / 5)
  4 confluence     number of timeframes (and pivots) that formed the zone
  5 volume         NOT used: spot gold has no consolidated volume; tick volume is not volume (documented)
  6 breaks         clean breaks through the zone vs. failed breaks (closed beyond, then back inside)
  7 ATR distance   used for ordering and by the decision engine (not part of intrinsic strength)
  8 role flip      the zone has acted both as support and as resistance

Weights are learned on historical "level test" events with purged walk-forward validation: a test HOLDS if the
price moves >= 1 ATR away before closing >= 0.5 ATR beyond the zone (within 12 H1 bars). Validation compares
out-of-sample AUC with a tests-only baseline. The displayed strength is a PERCENTILE RANK of the model score
versus historical levels ("stronger than x % of past levels"). When the validation fails or data are thin, only a
coarse label (weak / medium / strong) is shown.

Hold probability (pre-registered 2026-11-15, before any result): "if the price reaches this zone, P(it holds) as defined
above, within 12 H1 bars". Shown ONLY when, on the same out-of-sample folds, the ranking is validated AND
  * Brier skill vs the training base rate has a 99 % day-block bootstrap CI above zero, and
  * every probability bin with >= 200 events has |predicted - actual| <= 5 points.
Otherwise no probability is shown (the percentile strength above is unaffected).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import atr

TF_MIN = {"M15": 15, "H1": 60, "H4": 240}
PIVOT_K = {"M15": 4, "H1": 3, "H4": 2}
LOOKBACK_DAYS = {"M15": 10, "H1": 60, "H4": 200}
ZONE_TOL_ATR = 0.35
TOUCH_TOL_ATR = 0.10
REACT_BARS = 8
LABEL_BARS = 12
HOLD_ATR, BREAK_ATR = 1.0, 0.5
FEATURES = ["log_tests", "rejection", "recency", "confluence", "tf_count", "failed_breaks", "clean_breaks", "role_flip"]
MIN_EVENTS = 300
MIN_USEFUL_AUC = 0.55  # below this the ranking is statistically real but too weak to show as a number


# ------------------------------------------------------------------ pivots and zones
def pivots(df: pd.DataFrame, tf: str, k: int | None = None) -> pd.DataFrame:
    """Swing highs/lows. known_at = close time of bar i+k (the pivot cannot be confirmed earlier)."""
    k = k or PIVOT_K[tf]
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    rows = []
    for i in range(k, n - k):
        win_h, win_l = h[i - k:i + k + 1], l[i - k:i + k + 1]
        if h[i] == win_h.max() and (win_h == h[i]).sum() == 1:
            rows.append((df.index[i], h[i], -1))  # swing high -> resistance-type origin
        if l[i] == win_l.min() and (win_l == l[i]).sum() == 1:
            rows.append((df.index[i], l[i], +1))  # swing low -> support-type origin
    out = pd.DataFrame(rows, columns=["time", "price", "origin"])
    if out.empty:
        return out.assign(known_at=pd.Series(dtype="datetime64[ns, UTC]"), tf=tf)
    pos = df.index.get_indexer(out["time"])
    known_idx = np.minimum(pos + k, n - 1)
    out["known_at"] = df.index[known_idx] + pd.Timedelta(minutes=TF_MIN[tf])
    out["tf"] = tf
    return out


@dataclass
class Zone:
    low: float
    high: float
    center: float
    pivots: int
    tfs: tuple
    first_known: pd.Timestamp
    features: dict = field(default_factory=dict)
    score: float | None = None
    strength: int | None = None
    label: str = ""
    role: str = ""  # SUPPORT | RESISTANCE
    distance_atr: float = 0.0
    broken_recently: bool = False
    hold_p: float | None = None


def build_zones(piv: pd.DataFrame, tol: float) -> list[Zone]:
    if piv.empty:
        return []
    p = piv.sort_values("price").reset_index(drop=True)
    zones, start = [], 0
    prices = p["price"].to_numpy()
    for i in range(1, len(p) + 1):
        if i == len(p) or prices[i] - prices[i - 1] > tol:
            g = p.iloc[start:i]
            zones.append(Zone(float(g["price"].min()), float(g["price"].max()), float(g["price"].mean()), len(g),
                              tuple(sorted(set(g["tf"]))), g["known_at"].min()))
            start = i
    return zones


# ------------------------------------------------------------------ band features (shared by training and live use)
def band_features(h: np.ndarray, l: np.ndarray, c: np.ndarray, a: np.ndarray, times: pd.DatetimeIndex,
                  lo: float, hi: float, start: int, end: int, pivots_n: int, tf_count: int) -> dict:
    """Features of band [lo, hi] using bars [start, end) only."""
    f = {"tests": 0, "rejection": 0.0, "recency": 0.0, "confluence": float(pivots_n), "tf_count": float(tf_count),
         "failed_breaks": 0.0, "clean_breaks": 0.0, "role_flip": 0.0, "last_break_idx": -1, "last_test_idx": -1}
    if end - start < 3:
        f["log_tests"] = 0.0
        return f
    seg = slice(start, end)
    tol = TOUCH_TOL_ATR * np.nan_to_num(a[seg], nan=np.nanmean(a[seg]) if np.isfinite(np.nanmean(a[seg])) else 0.0)
    touch = (l[seg] <= hi + tol) & (h[seg] >= lo - tol)
    idx = np.flatnonzero(touch) + start
    tests, last_t, sides, rej = [], -10, set(), []
    for j in idx:
        if j - last_t >= 4 and j > 0:
            side = 1 if c[j - 1] > hi else (-1 if c[j - 1] < lo else 0)
            tests.append((j, side))
        last_t = j
    for j, side in tests:
        if side == 0:
            continue
        sides.add(side)
        stop = min(end, j + 1 + REACT_BARS)
        if stop <= j + 1:
            continue
        aj = a[j] if np.isfinite(a[j]) and a[j] > 0 else np.nanmean(a[seg])
        if side > 0:
            away = (np.max(h[j + 1:stop]) - hi) / aj
            beyond = np.flatnonzero(c[j:stop] < lo - BREAK_ATR * aj)
        else:
            away = (lo - np.min(l[j + 1:stop])) / aj
            beyond = np.flatnonzero(c[j:stop] > hi + BREAK_ATR * aj)
        rej.append(max(0.0, float(away)))
        if len(beyond):
            b = j + beyond[0]
            back = c[b + 1:min(end, b + 4)]
            inside = ((back <= hi) & (back >= lo)) | ((back > hi) if side > 0 else (back < lo))
            if len(back) and inside.any():
                f["failed_breaks"] += 1
            else:
                f["clean_breaks"] += 1
                f["last_break_idx"] = int(b)
    f["tests"] = len(tests)
    f["last_test_idx"] = int(tests[-1][0]) if tests else -1
    f["log_tests"] = float(np.log1p(len(tests)))
    f["rejection"] = float(np.mean(rej)) if rej else 0.0
    if tests:
        days = (times[end - 1] - times[tests[-1][0]]).total_seconds() / 86400
        f["recency"] = float(np.exp(-days / 5.0))
    f["role_flip"] = 1.0 if len(sides) == 2 else 0.0
    return f


# ------------------------------------------------------------------ event dataset + walk-forward validation
def level_events(h1: pd.DataFrame, piv: pd.DataFrame, max_tests_per_pivot: int = 5) -> pd.DataFrame:
    """One row per fresh approach of a known pivot band; features from the past, label from the future."""
    h, l, c = (h1[k].to_numpy() for k in ("high", "low", "close"))
    a = atr(h1).to_numpy()
    times = h1.index
    close_t = times + pd.Timedelta(minutes=60)
    rows = []
    known_pos = close_t.searchsorted(piv["known_at"].to_numpy(), side="left")
    allp = piv["price"].to_numpy()
    for p_i, (price, kp) in enumerate(zip(allp, known_pos)):
        if kp >= len(h1) - 2:
            continue
        ak = a[kp] if np.isfinite(a[kp]) else np.nanmean(a)
        lo, hi = price - 0.5 * ZONE_TOL_ATR * ak, price + 0.5 * ZONE_TOL_ATR * ak
        conf_mask = (np.abs(allp - price) <= ZONE_TOL_ATR * ak) & (known_pos <= kp)
        confluence = int(conf_mask.sum())
        tf_count = len(set(piv["tf"].to_numpy()[conf_mask]))
        n_ev = 0
        last = len(h1) - LABEL_BARS
        cand = np.flatnonzero((l[kp + 1:last] <= hi) & (h[kp + 1:last] >= lo)) + kp + 1
        for t in cand:
            if n_ev >= max_tests_per_pivot:
                break
            side = 1 if c[t - 1] > hi else (-1 if c[t - 1] < lo else 0)
            if side == 0:
                continue
            at = a[t]
            if not np.isfinite(at) or at <= 0:
                continue
            fwd_h, fwd_l, fwd_c = h[t + 1:t + 1 + LABEL_BARS], l[t + 1:t + 1 + LABEL_BARS], c[t + 1:t + 1 + LABEL_BARS]
            if side > 0:
                hold_i = np.flatnonzero(fwd_h >= hi + HOLD_ATR * at)
                brk_i = np.flatnonzero(fwd_c < lo - BREAK_ATR * at)
            else:
                hold_i = np.flatnonzero(fwd_l <= lo - HOLD_ATR * at)
                brk_i = np.flatnonzero(fwd_c > hi + BREAK_ATR * at)
            hold = bool(len(hold_i) and (not len(brk_i) or hold_i[0] < brk_i[0]))
            f = band_features(h, l, c, a, times, lo, hi, kp, t, confluence, tf_count)
            rows.append({"time": close_t[t], "label_known_at": close_t[min(t + LABEL_BARS, len(h1) - 1)],
                         "side": side, "hold": int(hold), **{k: f[k] for k in FEATURES}, "tests": f["tests"]})
            n_ev += 1
    return pd.DataFrame(rows).sort_values("time").reset_index(drop=True) if rows else pd.DataFrame()


def _model():
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=500))


def _auc(y: np.ndarray, s: np.ndarray) -> float:
    """ROC AUC as the Mann-Whitney statistic with average ranks for ties: the same number as sklearn's
    roc_auc_score for binary labels, without its per-call input checks (the bootstrap calls it 300 times, which on the
    free server's 0.1 CPU took most of a minute per asset)."""
    from scipy.stats import rankdata
    y = np.asarray(y).astype(bool)
    n1 = int(y.sum())
    n0 = len(y) - n1
    r = rankdata(np.asarray(s, dtype=float))
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def validate(ev: pd.DataFrame, n_folds: int = 5, seed: int = 0) -> dict:
    """Purged walk-forward: every fold trains only on events whose label was known before the fold starts."""
    if len(ev) < MIN_EVENTS or ev["hold"].nunique() < 2:
        return {"validated": False, "n_events": int(len(ev)), "reason_ar": "أحداث اختبار المستويات غير كافية"}
    t = ev["time"]
    edges = [t.quantile(q) for q in np.linspace(0.4, 1.0, n_folds + 1)]
    ps, bs, ys, brs = [], [], [], []
    for a_, b_ in zip(edges[:-1], edges[1:]):
        tr = ev[ev["label_known_at"] < a_]
        te = ev[(t >= a_) & (t < b_)]
        if len(tr) < 100 or te.empty or tr["hold"].nunique() < 2:
            continue
        m = _model().fit(tr[FEATURES].to_numpy(), tr["hold"].to_numpy())
        ps.append(m.predict_proba(te[FEATURES].to_numpy())[:, 1])
        bs.append(te["tests"].to_numpy(float))
        ys.append(te["hold"].to_numpy())
        brs.append(np.full(len(te), float(tr["hold"].mean())))
    if not ps:
        return {"validated": False, "n_events": int(len(ev)), "reason_ar": "لم يكتمل التحقق المتدرج"}
    p, b, y = np.concatenate(ps), np.concatenate(bs), np.concatenate(ys)
    if len(np.unique(y)) < 2:
        return {"validated": False, "n_events": int(len(ev)), "reason_ar": "نتائج الاختبار من صنف واحد"}
    auc, auc_b = roc_auc_score(y, p), roc_auc_score(y, b) if len(np.unique(b)) > 1 else 0.5
    # day-block bootstrap: tests of nearby levels on the same day are not independent
    days = np.concatenate([ev[(t >= a_) & (t < b_)]["time"].dt.floor("D").to_numpy()
                           for a_, b_ in zip(edges[:-1], edges[1:])
                           if len(ev[ev["label_known_at"] < a_]) >= 100 and not ev[(t >= a_) & (t < b_)].empty
                           and ev[ev["label_known_at"] < a_]["hold"].nunique() >= 2])
    uniq = np.unique(days)
    groups = [np.flatnonzero(days == d) for d in uniq]
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(300):
        i = np.concatenate([groups[g] for g in rng.integers(0, len(groups), len(groups))])
        if len(np.unique(y[i])) == 2:
            boots.append(_auc(y[i], p[i]))
    lo, hi = float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))
    ok = len(y) >= MIN_EVENTS and lo > 0.5 and auc > auc_b and auc >= MIN_USEFUL_AUC
    cal = probability_calibration(p, y, np.concatenate(brs), groups, rng)
    return {"validated": bool(ok), "prob_calibrated": bool(ok and cal["ok"]), "calibration": cal, "n_events": int(len(ev)), "n_oos": int(len(y)), "auc_oos": round(float(auc), 4),
            "auc_oos_ci95": [round(lo, 4), round(hi, 4)], "auc_baseline_tests_only": round(float(auc_b), 4),
            "base_hold_rate": round(float(y.mean()), 4),
            "reason_ar": "الأوزان تفوقت على عدد الاختبارات وحده خارج العينة" if ok else
            "الأوزان لم تثبت تفوقاً خارج العينة — تُعرض تصنيفات تقديرية فقط"}


def probability_calibration(p, y, base, groups, rng, level=99.0) -> dict:
    ea, eb = (p - y) ** 2, (base - y) ** 2
    skill = float(1 - ea.sum() / eb.sum()) if eb.sum() > 0 else 0.0
    boots = []
    for _ in range(500):
        i = np.concatenate([groups[g] for g in rng.integers(0, len(groups), len(groups))])
        if eb[i].sum() > 0:
            boots.append(1 - ea[i].sum() / eb[i].sum())
    q = (100 - level) / 2
    ci = [round(float(np.percentile(boots, q)), 4), round(float(np.percentile(boots, 100 - q)), 4)] if boots else None
    bins = []
    for lo_, hi_ in ((0, .3), (.3, .45), (.45, .55), (.55, .7), (.7, 1.01)):
        m = (p >= lo_) & (p < hi_)
        if m.sum():
            bins.append({"bin": f"{int(lo_ * 100)}-{min(100, int(hi_ * 100))}%", "n": int(m.sum()),
                         "predicted": round(float(p[m].mean()), 4), "actual": round(float(y[m].mean()), 4)})
    calibrated = all(abs(b["predicted"] - b["actual"]) <= 0.05 for b in bins if b["n"] >= 200)
    return {"brier_skill": round(skill, 4), "brier_skill_ci99": ci, "bins": bins,
            "ok": bool(ci is not None and ci[0] > 0 and calibrated)}


# ------------------------------------------------------------------ live service
HEURISTIC_W = {"log_tests": 0.8, "rejection": 0.8, "recency": 0.5, "confluence": 0.3, "tf_count": 0.6,
               "failed_breaks": 0.4, "clean_breaks": -0.6, "role_flip": 0.3}


@dataclass
class LevelModel:
    model: object | None
    reference_scores: np.ndarray
    validation: dict
    trained_until: datetime | None


def _score(model: LevelModel, feats: dict) -> float:
    x = np.array([[feats[k] for k in FEATURES]], dtype=float)
    if model.model is not None:
        return float(model.model.decision_function(x)[0])
    return float(sum(HEURISTIC_W[k] * feats[k] for k in FEATURES))


def train_level_model(h1: pd.DataFrame, piv: pd.DataFrame, as_of) -> LevelModel:
    ev = level_events(h1, piv)
    ev = ev[ev["label_known_at"] <= pd.Timestamp(as_of)] if len(ev) else ev
    val = validate(ev) if len(ev) else {"validated": False, "n_events": 0, "reason_ar": "لا توجد أحداث"}
    if len(ev) and ev["hold"].nunique() == 2:
        m = _model().fit(ev[FEATURES].to_numpy(), ev["hold"].to_numpy())
        ref = m.decision_function(ev[FEATURES].to_numpy())
        return LevelModel(m if val["validated"] else None,
                          ref if val["validated"] else ev[FEATURES].apply(lambda r: sum(HEURISTIC_W[k] * r[k] for k in FEATURES), axis=1).to_numpy(),
                          val, as_of)
    return LevelModel(None, np.array([]), val, as_of)


def compute_levels(bars: dict, as_of, price: float, model: LevelModel | None = None, n: int = 3) -> dict:
    """Zones as of `as_of` (only pivots already confirmed), strength scored with `model`.
    Every window is anchored to as_of and bars not closed by as_of are dropped, so later data cannot leak in."""
    ts = pd.Timestamp(as_of)
    bars = {tf: df[df.index + pd.Timedelta(minutes=TF_MIN[tf]) <= ts] for tf, df in bars.items() if tf in TF_MIN}
    h1 = bars["H1"]
    a_h1 = atr(h1)
    atr_now = float(a_h1.iloc[-1]) if len(a_h1) and np.isfinite(a_h1.iloc[-1]) else float((h1["high"] - h1["low"]).tail(50).mean())
    allp = []
    for tf in ("M15", "H1", "H4"):
        df = bars.get(tf)
        if df is None or df.empty:
            continue
        df = df[df.index >= ts - pd.Timedelta(days=LOOKBACK_DAYS[tf])]
        p = pivots(df, tf)
        allp.append(p[p["known_at"] <= pd.Timestamp(as_of)])
    piv = pd.concat(allp) if allp else pd.DataFrame()
    zones = build_zones(piv, ZONE_TOL_ATR * atr_now)
    h, l, c = (h1[k].to_numpy() for k in ("high", "low", "close"))
    a = a_h1.to_numpy()
    times = h1.index
    close_t = times + pd.Timedelta(minutes=60)
    end = int(close_t.searchsorted(pd.Timestamp(as_of), side="right"))
    model = model or LevelModel(None, np.array([]), {"validated": False, "reason_ar": "بدون نموذج"}, None)
    ref = model.reference_scores
    out_s, out_r = [], []
    for z in zones:
        pad = 0.5 * ZONE_TOL_ATR * atr_now * 0.5  # same band half-width as training events
        lo, hi = z.low - pad, z.high + pad
        start = max(0, int(close_t.searchsorted(z.first_known, side="left")))
        f = band_features(h, l, c, a, times, lo, hi, start, end, z.pivots, len(z.tfs))
        z.features = {k: (round(float(v), 3) if isinstance(v, float) else v) for k, v in f.items()}
        z.score = _score(model, f)
        pct = float((ref <= z.score).mean() * 100) if len(ref) >= 50 else None
        z.strength = int(round(pct)) if (pct is not None and model.validation.get("validated")) else None
        z.hold_p = None
        if model.model is not None and model.validation.get("prob_calibrated"):
            z.hold_p = round(float(model.model.predict_proba(np.array([[f[k] for k in FEATURES]], float))[0, 1]), 3)
        bucket = pct if pct is not None else None
        z.label = ("قوي" if bucket >= 67 else "متوسط" if bucket >= 34 else "ضعيف") if bucket is not None else "غير مُقيَّم"
        z.distance_atr = round((z.center - price) / atr_now, 2) if atr_now > 0 else 0.0
        if z.high < price:
            z.role = "SUPPORT"
            out_s.append(z)
        elif z.low > price:
            z.role = "RESISTANCE"
            out_r.append(z)
        lb = f["last_break_idx"]
        lt = f["last_test_idx"]
        z.last_test_utc = (times[lt].to_pydatetime().isoformat().replace("+00:00", "Z")
                           if lt >= 0 else None)
        z.broken_recently = bool(lb >= 0 and end - lb <= 48)
    out_s.sort(key=lambda z: price - z.center)
    out_r.sort(key=lambda z: z.center - price)
    to_d = lambda z, k: {"name": f"{k}", "price": round(z.center, 2), "zone_low": round(z.low, 2), "zone_high": round(z.high, 2),  # noqa
                         "strength": z.strength, "strength_label_ar": z.label, "tests": int(z.features.get("tests", 0)),
                         "timeframes": list(z.tfs), "role_flip": bool(z.features.get("role_flip")),
                         "broken_recently": z.broken_recently, "distance_atr": z.distance_atr,
                         "last_test_utc": getattr(z, "last_test_utc", None),
                         "hold_probability": getattr(z, "hold_p", None)}
    return {"supports": [to_d(z, f"S{i + 1}") for i, z in enumerate(out_s[:n])],
            "resistances": [to_d(z, f"R{i + 1}") for i, z in enumerate(out_r[:n])],
            "atr_h1": round(atr_now, 3), "validated": bool(model.validation.get("validated")),
            "validation": model.validation,
            "method_note_ar": ("القوة = ترتيب مئيني مقارنة بالمستويات التاريخية، وليست احتمال ارتداد. "
                               "الحجم غير مستخدم لأن الذهب الفوري لا يملك حجماً موحداً حقيقياً.")}


class LevelService:
    """Strength model cache. A model may be reused for up to REUSE hours AFTER it was trained (never before:
    a model trained on later data is not used for an earlier decision). Cloud mode injects a CI-trained model."""
    REUSE = pd.Timedelta(hours=24)

    def __init__(self):
        self._models: dict = {}
        self._lock = threading.Lock()
        self.prebuilt: LevelModel | None = None

    def set_prebuilt(self, m: LevelModel | None) -> None:
        self.prebuilt = m

    def _usable(self, m: LevelModel, as_of) -> bool:
        if m is None or m.trained_until is None:
            return False
        d = pd.Timestamp(as_of) - pd.Timestamp(m.trained_until)
        return pd.Timedelta(0) <= d <= self.REUSE

    def model(self, key, bars: dict, as_of) -> LevelModel:
        if self._usable(self.prebuilt, as_of):
            return self.prebuilt
        # Train once per UTC day on data known at 00:00 of that day: deterministic and point-in-time safe.
        as_of = pd.Timestamp(as_of).floor("D").to_pydatetime()
        with self._lock:
            for m in self._models.get(key, []):
                if m.trained_until is not None and pd.Timestamp(m.trained_until) == pd.Timestamp(as_of):
                    return m
        h1 = bars["H1"]
        piv = pd.concat([pivots(bars[tf], tf) for tf in ("M15", "H1", "H4") if tf in bars and len(bars[tf])])
        piv = piv[piv["known_at"] <= pd.Timestamp(as_of)]
        m = train_level_model(h1[h1.index + pd.Timedelta(minutes=60) <= pd.Timestamp(as_of)], piv, as_of)
        with self._lock:
            lst = self._models.setdefault(key, [])
            lst.append(m)
            del lst[:-12]
        return m
