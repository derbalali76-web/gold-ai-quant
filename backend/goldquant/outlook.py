"""Multi-horizon outlook: WEEK (5 trading days) and MONTH (21 trading days) on DAILY bars.

Design rules (same honesty contract as the intraday engine):
* Each horizon uses ONE fixed, pre-declared rule (no parameter search), computed only from daily bars that
  closed at or before as_of. The rule is then evaluated on the full available history BEFORE as_of with
  NON-overlapping holding periods, net of a round-trip cost.
* A horizon is "validated" only if: enough non-overlapping signals, the hit rate beats the unconditional base
  rate with a one-sided test (Bonferroni over the two horizons), the edge is positive in BOTH halves of the
  history, and the mean signed return after costs is positive.
* Only a validated rule may output BUY/SELL. An unvalidated rule outputs WAIT with its tilt shown in words.
* The reported hit rate is a historical FREQUENCY of the rule (not a calibrated probability of this trade).
* Stops/targets are ATR-scaled risk guides; they are NOT part of the validation (close-to-close returns).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from .msg import M, Msg

OUTLOOK_VERSION = "outlook-1.0"
HORIZON_DAYS = {"WEEK": 5, "MONTH": 21}
LABEL_AR = {"HOURS": "ساعات", "WEEK": "أسبوع", "MONTH": "شهر"}
MIN_DAILY_BARS = 300
MIN_SIGNALS = {"WEEK": 60, "MONTH": 40}
ALPHA = 0.05 / 2  # Bonferroni over the two daily horizons
ROUND_TRIP_COST = 0.0003  # 0.03 % of price: spread + slippage, conservative for spot gold
STOP_ATR = {"WEEK": 1.5, "MONTH": 2.5}
TARGET_ATR = {"WEEK": 2.5, "MONTH": 4.5}
RULE_AR = {
    "WEEK": ("شراء التراجع داخل اتجاه صاعد (السعر فوق متوسط 200 يوم وزخم 6 أشهر موجب، مع إغلاق تحت متوسط 20 "
             "يوماً و RSI14 أقل من 45)، والعكس للبيع"),
    "MONTH": "اتفاق زخم 3 و6 و12 شهراً في الاتجاه نفسه مع موقع السعر من متوسط 200 يوم",
}


@dataclass
class RuleStats:
    n: int = 0
    hits: int = 0
    hit_rate: Optional[float] = None
    base_rate: Optional[float] = None
    mean_signed_return: Optional[float] = None
    p_value: Optional[float] = None
    half_edges: list = field(default_factory=list)
    validated: bool = False
    reason_ar: str = ""
    reason_msg: Optional[Msg] = None
    period: Optional[str] = None


@dataclass
class HorizonView:
    horizon: str
    action: str  # BUY | SELL | WAIT | UNAVAILABLE
    tilt: int  # -1 / 0 / +1 — the rule's raw view, shown in words when not validated
    stance_ar: str
    reason_ar: str
    validated: bool
    validation_ar: str
    stats: RuleStats
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    wait_for_price: Optional[float] = None
    warnings_ar: list = field(default_factory=list)
    stance_msg: Optional[Msg] = None
    reason_msg: Optional[Msg] = None
    validation_msg: Optional[Msg] = None
    facts: list = field(default_factory=list)  # list[Msg]
    levels: Optional[dict] = None
    trend: Optional[dict] = None


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def daily_features(d: pd.DataFrame) -> pd.DataFrame:
    """Row t uses only daily bars up to and including t (valid at t's close)."""
    c = d["close"]
    out = pd.DataFrame(index=d.index)
    out["close"] = c
    out["sma20"] = c.rolling(20).mean()
    out["sma50"] = c.rolling(50).mean()
    out["sma200"] = c.rolling(200).mean()
    prev = c.shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - prev).abs(), (d["low"] - prev).abs()], axis=1).max(axis=1)
    out["atr20"] = tr.rolling(20).mean()
    out["rsi14"] = _rsi(c)
    lc = np.log(c)
    for k in (63, 126, 252):
        out[f"mom{k}"] = lc - lc.shift(k)
    return out


def rule_signals(f: pd.DataFrame, horizon: str) -> pd.Series:
    """Vectorised fixed rule -> +1 / -1 / 0 per day (NaN features -> 0)."""
    if horizon == "WEEK":
        up = (f["close"] > f["sma200"]) & (f["mom126"] > 0)
        dn = (f["close"] < f["sma200"]) & (f["mom126"] < 0)
        dip = (f["close"] < f["sma20"]) & (f["rsi14"] < 45)
        pop = (f["close"] > f["sma20"]) & (f["rsi14"] > 55)
        s = np.where(up & dip, 1, np.where(dn & pop, -1, 0))
    elif horizon == "MONTH":
        votes = np.sign(f["mom63"]) + np.sign(f["mom126"]) + np.sign(f["mom252"])
        s = np.where((votes == 3) & (f["close"] > f["sma200"]), 1,
                     np.where((votes == -3) & (f["close"] < f["sma200"]), -1, 0))
    else:
        raise ValueError(horizon)
    return pd.Series(s, index=f.index).where(f[["sma200", "mom126"]].notna().all(axis=1), 0).fillna(0).astype(int)


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def evaluate_rule(f: pd.DataFrame, sig: pd.Series, horizon: str) -> RuleStats:
    """Non-overlapping evaluation on the given (already as-of filtered) history."""
    h = HORIZON_DAYS[horizon]
    close = f["close"].to_numpy()
    s = sig.to_numpy()
    n_rows = len(close)
    if n_rows < MIN_DAILY_BARS:
        m = M("va.insufficient", n_rows, MIN_DAILY_BARS)
        return RuleStats(reason_ar=str(m), reason_msg=m)
    fwd = np.full(n_rows, np.nan)
    fwd[:-h] = np.log(close[h:] / close[:-h])  # outcome known only h days later; last h rows have none
    # unconditional base: every h-th window over the same span
    base_idx = np.arange(0, n_rows - h, h)
    base = fwd[base_idx]
    base = base[np.isfinite(base)]
    p_up = float(np.mean(base > ROUND_TRIP_COST)) if len(base) else 0.5
    p_dn = float(np.mean(-base > ROUND_TRIP_COST)) if len(base) else 0.5
    taken, last = [], -10**9
    for i in range(n_rows - h):
        if s[i] != 0 and i >= last + h and np.isfinite(fwd[i]):
            taken.append(i)
            last = i
    n = len(taken)
    st = RuleStats(n=n, base_rate=round((p_up + p_dn) / 2, 4))
    if n == 0:
        st.reason_msg = M("va.no_signals")
        st.reason_ar = str(st.reason_msg)
        return st
    idx = np.array(taken)
    signed = s[idx] * fwd[idx] - ROUND_TRIP_COST
    hit = signed > 0
    p_i = np.where(s[idx] > 0, p_up, p_dn)
    st.hits = int(hit.sum())
    st.hit_rate = round(float(hit.mean()), 4)
    st.base_rate = round(float(p_i.mean()), 4)
    st.mean_signed_return = round(float(signed.mean()), 5)
    var = float(np.sum(p_i * (1 - p_i)))
    z = (st.hits - float(p_i.sum())) / math.sqrt(var) if var > 0 else 0.0
    st.p_value = round(_norm_sf(z), 4)
    half = n // 2
    for part in (slice(0, half), slice(half, n)):
        st.half_edges.append(round(float(hit[part].mean() - p_i[part].mean()), 4) if len(hit[part]) else None)
    st.period = f"{f.index[0].date()} → {f.index[min(idx[-1] + h, n_rows - 1)].date()}"
    ok_n = n >= MIN_SIGNALS[horizon]
    ok_p = st.p_value < ALPHA
    ok_half = all(e is not None and e > 0 for e in st.half_edges)
    ok_ret = st.mean_signed_return > 0
    st.validated = ok_n and ok_p and ok_half and ok_ret
    if st.validated:
        st.reason_msg = M("va.validated")
    elif not ok_n:
        st.reason_msg = M("va.few", n, MIN_SIGNALS[horizon])
    elif not ok_p:
        st.reason_msg = M("va.pvalue", f"{st.p_value:.3f}")
    elif not ok_half:
        st.reason_msg = M("va.unstable")
    else:
        st.reason_msg = M("va.neg_return")
    st.reason_ar = str(st.reason_msg)
    return st


def _view(horizon: str, f: pd.DataFrame, sig: pd.Series, stats: RuleStats, synthetic: bool) -> HorizonView:
    r = f.iloc[-1]
    tilt = int(sig.iloc[-1])
    price, atr = float(r["close"]), float(r["atr20"])
    side = {1: M("w.buying"), -1: M("w.selling")}.get(tilt)
    trend_up = r["close"] > r["sma200"] and r["mom126"] > 0
    trend_dn = r["close"] < r["sma200"] and r["mom126"] < 0
    big = M("bt.up") if trend_up else (M("bt.down") if trend_dn else M("bt.mixed"))
    val = M("va.full", stats.reason_msg or stats.reason_ar, M("w.synthetic") if synthetic else M("w.none"),
            M("va.samples", stats.n, stats.period or "") if (stats.n and stats.hit_rate is not None) else M("w.none"))
    v = HorizonView(horizon=horizon, action="WAIT", tilt=tilt, stance_ar="انتظار", reason_ar="", validated=stats.validated,
                    validation_ar=str(val), stats=stats, stance_msg=M("st.wait"), validation_msg=val)
    sma20, rsi = f"{r['sma20']:.2f}", f"{r['rsi14']:.0f}"
    if horizon == "WEEK":
        if tilt > 0:
            v.reason_msg = M("ow.dip_buy", big, sma20, rsi)
        elif tilt < 0:
            v.reason_msg = M("ow.pop_sell", big, sma20, rsi)
        elif trend_up:
            v.reason_msg = M("ow.up_no_dip", big)
            v.wait_for_price = round(min(float(r["sma20"]), price - 0.5 * atr), 2)
        elif trend_dn:
            v.reason_msg = M("ow.down_no_pop", big)
            v.wait_for_price = round(max(float(r["sma20"]), price + 0.5 * atr), 2)
        else:
            v.reason_msg = M("ow.no_edge", big)
    else:
        moms = [("om.p3", r["mom63"]), ("om.p6", r["mom126"]), ("om.p12", r["mom252"])]
        txt = "، ".join(str(M("om.mom_item", M(c), "+" if m > 0 else "−", f"{abs(m) * 100:.1f}")) for c, m in moms if m == m)
        if tilt:
            v.reason_msg = M("om.agree", txt, M("w.above") if tilt > 0 else M("w.below"), f"{r['sma200']:.2f}")
        else:
            v.reason_msg = M("om.disagree", txt)
    v.reason_ar = str(v.reason_msg)
    v.facts = [M("fa.price_sma", M("w.above") if r["close"] > r["sma200"] else M("w.below"), f"{r['sma200']:.2f}",
                 f"{abs(r['close'] / r['sma200'] - 1) * 100:.1f}"),
               M("fa.sma20", sma20), M("fa.rsi", rsi),
               M("fa.mom", M("om.p6"), f"{r['mom126'] * 100:+.1f}"), M("fa.atr", f"{atr:.2f}")]
    if tilt:
        k_sl, k_tp = STOP_ATR[horizon], TARGET_ATR[horizon]
        v.entry_price = round(price, 2)
        v.stop_loss = round(price - tilt * k_sl * atr, 2)
        v.target = round(price + tilt * k_tp * atr, 2)
        if stats.validated:
            v.action = "BUY" if tilt > 0 else "SELL"
            v.stance_msg = M(("st.buy_dip" if horizon == "WEEK" else "st.buy_trend") if tilt > 0 else
                             ("st.sell_pop" if horizon == "WEEK" else "st.sell_trend"))
        else:
            v.stance_msg = M("st.lean_buy" if tilt > 0 else "st.lean_sell")
            v.warnings_ar.append(M("wa.unvalidated"))
        v.warnings_ar.append(M("wa.atr_levels", f"{atr:.2f}"))
    v.stance_ar = str(v.stance_msg)
    return v


def daily_levels(daily: pd.DataFrame, price: float, n: int = 3, window: int = 5, lookback: int = 250) -> dict:
    """Support/resistance from confirmed DAILY swing highs/lows (fractal window each side, so a pivot is known only
    `window` days after it formed). Zones are clustered by ATR proximity. No numeric strength is produced
    (not statistically validated); `tests` = number of separate approaches. Daily timeframes only."""
    d = daily.tail(lookback)
    f = daily_features(d)
    atr = float(f["atr20"].iloc[-1]) if len(f) and np.isfinite(f["atr20"].iloc[-1]) else float((d["high"] - d["low"]).mean())
    h, l = d["high"].to_numpy(), d["low"].to_numpy()
    idx = d.index
    piv = []
    for i in range(window, len(d) - window):
        if h[i] == h[i - window:i + window + 1].max():
            piv.append((float(h[i]), i))
        if l[i] == l[i - window:i + window + 1].min():
            piv.append((float(l[i]), i))
    piv.sort()
    tol = 0.5 * atr
    zones: list[list] = []
    for p_, i in piv:
        if zones and p_ - zones[-1][-1][0] <= tol:
            zones[-1].append((p_, i))
        else:
            zones.append([(p_, i)])
    out_s, out_r = [], []
    for z in zones:
        lo, hi = min(p for p, _ in z), max(p for p, _ in z)
        center = float(np.mean([p for p, _ in z]))
        band_lo, band_hi = lo - 0.15 * atr, hi + 0.15 * atr
        touch = np.flatnonzero((l <= band_hi) & (h >= band_lo))
        tests, last_t, last_idx = 0, -10, -1
        for j in touch:
            if j - last_t >= 4:
                tests += 1
            last_t = j
            last_idx = int(j)
        info = {"price": round(center, 2), "zone_low": round(band_lo, 2), "zone_high": round(band_hi, 2),
                "tests": tests, "timeframes": ["D1"], "role_flip": False, "broken_recently": False,
                "last_test_utc": idx[last_idx].to_pydatetime().isoformat().replace("+00:00", "Z") if last_idx >= 0 else None,
                "distance_atr": round((center - price) / atr, 2) if atr > 0 else 0.0,
                "strength": None,
                "strength_label_ar": "قوي" if tests >= 5 else ("متوسط" if tests >= 3 else "ضعيف")}
        if band_hi < price:
            out_s.append(info)
        elif band_lo > price:
            out_r.append(info)
    out_s.sort(key=lambda z: price - z["price"])
    out_r.sort(key=lambda z: z["price"] - price)
    for k, z in enumerate(out_s[:n]):
        z["name"] = f"S{k + 1}"
    for k, z in enumerate(out_r[:n]):
        z["name"] = f"R{k + 1}"
    return {"supports": out_s[:n], "resistances": out_r[:n], "validated": False, "atr_h1": None,
            "validation_ar": None, "method_ref": M("lv.method_daily")}


def daily_trend_block(daily: pd.DataFrame, horizon: str) -> dict:
    """Per-horizon trend card from daily features. The 0-100 score is ANALYTIC (agreement of the checks), not a
    probability. Timeframe keys are daily-derived views, not intraday frames."""
    f = daily_features(daily).iloc[-1]
    checks = {"SMA20": f["close"] > f["sma20"], "SMA50": f["close"] > f["sma50"], "SMA200": f["close"] > f["sma200"],
              "MOM3M": f["mom63"] > 0, "MOM6M": f["mom126"] > 0, "MOM12M": f["mom252"] > 0}
    names = ["SMA20", "SMA50", "SMA200"] if horizon == "WEEK" else ["SMA200", "MOM3M", "MOM6M", "MOM12M"]
    ups = sum(1 for k in names if checks[k] is True or bool(checks[k]))
    n = len(names)
    direction = "UP" if ups == n else ("DOWN" if ups == 0 else "SIDEWAYS")
    agreement = round(max(ups, n - ups) / n, 2)
    strength = int(round(100 * agreement)) if direction != "SIDEWAYS" else int(round(50 * agreement))
    label = {"UP": "صاعد", "DOWN": "هابط", "SIDEWAYS": "عرضي"}[direction]
    return {"direction": direction, "strength": strength, "label_ar": label, "agreement": agreement,
            "per_timeframe": {k: ("UP" if bool(checks[k]) else "DOWN") for k in names}}


def compute(daily: Optional[pd.DataFrame], as_of: datetime, synthetic: bool = False,
            upcoming_events: Optional[list] = None, macro: Optional[dict] = None) -> list[HorizonView]:
    """daily: OHLC indexed by day OPEN time (UTC); only days CLOSED at or before as_of are used."""
    out = []
    if daily is not None and len(daily):
        daily = daily[daily.index + pd.Timedelta(days=1) <= pd.Timestamp(as_of)]
    n = 0 if daily is None else len(daily)
    for hz in ("WEEK", "MONTH"):
        if n < MIN_DAILY_BARS:
            msg = M("va.insufficient", n, MIN_DAILY_BARS)
            out.append(HorizonView(horizon=hz, action="UNAVAILABLE", tilt=0, stance_ar=str(M("st.na")), reason_ar=str(msg),
                                   validated=False, validation_ar=str(msg), stats=RuleStats(reason_ar=str(msg), reason_msg=msg),
                                   stance_msg=M("st.na"), reason_msg=msg, validation_msg=msg))
            continue
        f = daily_features(daily)
        sig = rule_signals(f, hz)
        stats = evaluate_rule(f, sig, hz)
        v = _view(hz, f, sig, stats, synthetic)
        try:
            v.levels = daily_levels(daily, float(f["close"].iloc[-1]))
        except Exception:  # levels are informative only; never break the outlook
            v.levels = None
        v.trend = daily_trend_block(daily, hz)
        for name in (upcoming_events or [])[:3]:
            v.warnings_ar.append(M("wa.event", name))
        if macro and v.tilt:
            ry = macro.get("DFII10")
            if ry and abs(ry.get("change_5obs", 0)) >= 0.10:
                rising = ry["change_5obs"] > 0
                if (v.tilt > 0 and rising) or (v.tilt < 0 and not rising):
                    v.warnings_ar.append(M("wa.real_yield"))
            usd = macro.get("DTWEXBGS")
            if usd and usd.get("value"):
                chg = usd.get("change_5obs", 0) / usd["value"]
                if abs(chg) >= 0.01 and ((v.tilt > 0 and chg > 0) or (v.tilt < 0 and chg < 0)):
                    v.warnings_ar.append(M("wa.usd"))
        out.append(v)
    return out


def daily_trend(daily: Optional[pd.DataFrame], as_of: datetime) -> int:
    """+1 / -1 when the big daily trend is clear (price vs SMA200 AND 6-month momentum agree), else 0."""
    if daily is None or len(daily) < 210:
        return 0
    d = daily[daily.index + pd.Timedelta(days=1) <= pd.Timestamp(as_of)]
    if len(d) < 210:
        return 0
    f = daily_features(d).iloc[-1]
    if f["close"] > f["sma200"] and f["mom126"] > 0:
        return 1
    if f["close"] < f["sma200"] and f["mom126"] < 0:
        return -1
    return 0
