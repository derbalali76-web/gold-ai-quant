"""Decision engine.

Pipeline: data-quality gates -> features -> regime (M15/H4) + volatility regime -> multi-timeframe bias ->
Probabilistic Path (3 outcomes x 4 horizons) -> critic -> drift sentinel -> uncertainty map ->
Anti-Trade gate -> risk levels -> Decision. WAIT is the default whenever anything is missing or conflicting.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from . import drift as DRIFT
from . import model as M
from . import path as P
from .bias import bias_score, direction as bias_direction
from .anti_trade import TradeCandidate, evaluate as anti_trade
from .context import MarketContext
from .paper import ledger_state
from .reliability import court as COURT
from .reliability import firewall as FW
from .reliability import governor as GOV
from .reliability import uncertainty_budget as UB
from .reliability.pit import PITLedger
from .critic import review
from .intel import analog as ANALOG
from .intel import counterfactual as CF
from .intel import liquidity_trap as TRAP
from . import level_rules as LR
from .levels import LevelService, compute_levels as compute_sr
from .trend import market_trend
from .features import frame_features, session_of
from .providers.base import MarketDataProvider
from .regime import VOL_REGIME_AR, classify, volatility_regime
from .risk import compute_levels, estimated_cost, stop_inside_structure
from .schemas import (Action, CourtJudgement, DataFreshness, Decision, Evidence, HorizonProbability, Mode,
                      SCHEMA_VERSION, SpotOrProxy, Uncertainty)
from .store import Store

MIN_BARS = {"M15": 600, "M30": 300, "H1": 200, "H4": 100}
FETCH_BARS = {"M15": 20000, "M30": 10000, "H1": 5000, "H4": 1500}
MAX_QUOTE_AGE_S = {Mode.DEMO: 180.0, Mode.LIVE: 180.0}
SIGNAL_VALIDITY = timedelta(minutes=15)
PRIMARY_HORIZON = 240
DRIFT_FEATURES = ["er20", "vr4", "vol_ratio", "range_z", "h1_er20", "h4_er20", "log_since_break"]
ENGINES_ACTIVE = ["data_quality", "volatility_regime", "mtf_bias", "probabilistic_path", "adversarial_critic",
                  "liquidity_trap", "structural_break(CUSUM)", "model_drift_sentinel", "uncertainty_map",
                  "historical_analog", "counterfactual", "anti_trade", "risk"]
CONTEXT_ENGINES = ["news_propagation", "economic_calendar", "institutional_footprint(COT)", "macro(FRED)",
                   "etf_flows(GLD)", "gold_volatility(GVZ)"]


@dataclass
class EngineConfig:
    require_news_calendar_live: bool = True
    news_calendar_connected: bool = False


@dataclass
class PathState:
    models: Optional[P.PathModels]
    qualified: bool
    reason_ar: str
    drift: Optional[DRIFT.DriftReport]
    ds: Optional[pd.DataFrame] = None
    fwd: Optional[pd.DataFrame] = None


class PathService:
    """Trains + validates the path models per (provider, hour) using only data known at as_of; caches."""

    def __init__(self):
        self._cache: dict = {}
        self._lock = threading.Lock()
        self.prebuilt: Optional[PathState] = None  # cloud mode: trained & validated by the CI job
        self.prebuilt_max_age = timedelta(hours=8)

    def set_prebuilt(self, state: Optional[PathState]) -> None:
        self.prebuilt = state

    def get(self, provider: MarketDataProvider, as_of: datetime, bars: dict) -> PathState:
        pb = self.prebuilt
        if pb is not None and pb.models is not None:
            tu = pd.Timestamp(pb.models.trained_until)
            if tu <= pd.Timestamp(as_of) and pd.Timestamp(as_of) - tu <= self.prebuilt_max_age:
                return pb  # never a model trained on data newer than the decision (PIT)
        key = (provider.meta.name, getattr(provider, "seed", None), as_of.replace(minute=0, second=0, microsecond=0))
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        ds = P.build_path_dataset(bars["M15"], bars["H1"], bars["H4"])
        fwd = CF.forward_extremes(bars["M15"])
        models = P.train_path_models(ds, as_of)
        if models is None or PRIMARY_HORIZON not in models.reports:
            st = PathState(models, False, "عينات تاريخية غير كافية لتدريب النموذج والتحقق منه", None, ds, fwd)
        else:
            rep = models.reports[PRIMARY_HORIZON]
            ts = pd.Timestamp(as_of)
            ref = ds[(ds["decision_time"] < ts - pd.Timedelta(days=10)) & (ds["decision_time"] >= ts - pd.Timedelta(days=70))]
            cur = ds[(ds["decision_time"] >= ts - pd.Timedelta(days=10)) & (ds["decision_time"] <= ts)]
            dr = DRIFT.check(ref, cur, DRIFT_FEATURES)
            st = PathState(models, rep.qualified, rep.reason, dr, ds, fwd)
        with self._lock:
            self._cache[key] = st
        return st


def minutes_to_weekly_close(now: datetime) -> float:
    days_ahead = (4 - now.weekday()) % 7
    close = (now + timedelta(days=days_ahead)).replace(hour=21, minute=0, second=0, microsecond=0)
    if close <= now:
        close += timedelta(days=7)
    return (close - now).total_seconds() / 60


def _snapshot(provider, mode, as_of, quote, bars) -> tuple[str, dict]:
    data = {"provider": provider.meta.name, "seed": getattr(provider, "seed", None), "mode": mode.value,
            "as_of": as_of.isoformat(), "model_version": M.MODEL_VERSION, "path_version": P.PATH_VERSION,
            "quote": None if quote is None else {"price": quote.price, "observed_at": quote.observed_at.isoformat()},
            "bars_tail": {tf: [[t.isoformat(), round(r.open, 5), round(r.high, 5), round(r.low, 5), round(r.close, 5)]
                               for t, r in b.tail(50).iterrows()] for tf, b in bars.items()}}
    h = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return h, data


def _reason(trend: dict, sr: dict | None, direction: int, blocker: str | None) -> str:
    """Exactly two short sentences: market context, then the deciding factor."""
    h4 = trend.get("per_timeframe", {}).get("H4", "محايد")
    first = f"اتجاه H4 {h4} والاتجاه العام {trend['label_ar']}"
    if sr:
        s1 = sr["supports"][0] if sr["supports"] else None
        r1 = sr["resistances"][0] if sr["resistances"] else None
        if direction > 0 and s1:
            first += f"، والسعر فوق الدعم {s1['price']:.2f}"
        elif direction < 0 and r1:
            first += f"، والسعر تحت المقاومة {r1['price']:.2f}"
        elif s1 and r1:
            first += f"، والسعر بين الدعم {s1['price']:.2f} والمقاومة {r1['price']:.2f}"
    if blocker is None:
        second = "العائد المتوقع بعد التكاليف موجب، واجتازت الإشارة محكمة القرار"
    else:
        second = "ننتظر لأن " + blocker.split("؛")[0].split(" — ")[0].rstrip(".")
    return f"{first}. {second}."


def _level(flags: int) -> str:
    return "LOW" if flags == 0 else ("MEDIUM" if flags == 1 else "HIGH")


class DecisionEngine:
    def __init__(self, store: Store, paths: PathService | None = None, config: EngineConfig | None = None,
                 precision=None, ledger=None, limits: GOV.GovernorLimits | None = None, registry=None, shadow=None):
        self.store = store
        self.ledger = ledger  # paper ledger: the risk governor's view of exposure and recent losses
        self.limits = limits or GOV.GovernorLimits()
        self.registry = registry  # model governance (rollback / safe mode)
        self.shadow = shadow  # shadow tournament book (LIVE only, never acts)
        self.level_service = LevelService()
        self.paths = paths or PathService()
        self.config = config or EngineConfig()
        self.precision = precision  # V3 PrecisionService (optional, strictly gated)

    def _unavailable(self, mode, provider, as_of, reason_ar, freshness, quote=None, missing=None,
                     snap_hash="none", spot=SpotOrProxy.NONE) -> Decision:
        did = hashlib.sha256(f"{snap_hash}|{mode.value}|{as_of.isoformat()}|U".encode()).hexdigest()[:16]
        return Decision(decision_id=did, mode=mode, action=Action.UNAVAILABLE,
                        spot_or_proxy=SpotOrProxy.SYNTHETIC if mode == Mode.DEMO else spot,
                        provider=provider.meta.name if provider else "none",
                        quote=None if quote is None else quote.price,
                        quote_timestamp_utc=None if quote is None else quote.observed_at,
                        analyzed_at_utc=as_of, model_version=P.PATH_VERSION, data_freshness=freshness,
                        data_quality="INSUFFICIENT", warning_ar=reason_ar, reason_short_ar=reason_ar,
                        missing_data=missing or [], snapshot_hash=snap_hash, engines_used=["data_quality"])

    def decide(self, provider: Optional[MarketDataProvider], mode: Mode, as_of: datetime,
               context: Optional[MarketContext] = None) -> Decision:
        max_age = MAX_QUOTE_AGE_S[mode]
        if provider is None:
            fr = DataFreshness(max_allowed_seconds=max_age, is_fresh=False)
            return self._finish(self._unavailable(
                mode, None, as_of, "لم يُضبط مزوّد بيانات حي بعد. استخدم الوضع التجريبي أو أضف مفتاحاً مجانياً.",
                fr, missing=["مزوّد سعر XAU/USD حي"]))
        quote = provider.quote(as_of)
        age = None if quote is None else quote.age_seconds(as_of)
        bars, counts, corrupt = {}, {}, []
        for tf in ("M15", "M30", "H1", "H4"):
            b = provider.bars(tf, as_of, FETCH_BARS[tf])
            if b is not None:
                try:
                    b.validate()
                    bars[tf] = b.df
                except ValueError as exc:
                    corrupt.append(f"{tf}: {exc}")
                    b = None
            counts[tf] = 0 if b is None else len(b.df)
        fresh = quote is not None and age is not None and 0 <= age <= max_age
        fr = DataFreshness(quote_age_seconds=age, max_allowed_seconds=max_age, is_fresh=fresh, bars_available=counts)
        snap_hash, snap = _snapshot(provider, mode, as_of, quote, bars)
        self.store.save_snapshot(snap_hash, as_of.isoformat(), snap)
        spot = SpotOrProxy(provider.meta.spot_or_proxy)
        session = session_of(pd.Timestamp(as_of))

        pit = PITLedger(as_of)
        if quote is not None:
            pit.add("quote", quote.observed_at, provider.meta.name)
        for tf_, df_ in bars.items():
            pit.add(f"last_closed_{tf_}_bar", df_.index[-1] + pd.Timedelta(minutes={"M15": 15, "M30": 30, "H1": 60, "H4": 240}[tf_]),
                    provider.meta.name)
        audit = {"pit": None, "firewall": None}

        def u(msg, missing=None):
            audit["pit"] = pit.summary()
            return self._finish(self._unavailable(mode, provider, as_of, msg, fr, quote, missing=missing,
                                                  snap_hash=snap_hash, spot=spot), audit)
        if corrupt:
            return u("بيانات المزوّد تالفة أو غير متسقة — رُفضت", corrupt)
        if quote is None:
            return u("لا يوجد سعر متاح من المزوّد")
        if session == "CLOSED":
            return u("سوق الذهب الفوري مغلق حالياً (عطلة نهاية الأسبوع)")
        if not fresh:
            return u(f"السعر قديم ({age:.0f} ثانية) — لا يُعتمد عليه")
        short = [tf for tf, n in MIN_BARS.items() if counts.get(tf, 0) < n]
        if short:
            return u("بيانات تاريخية غير كافية للتحليل", [f"شموع {tf}" for tf in short])

        # ---------------- features & regimes
        feats = {tf: frame_features(df) for tf, df in bars.items()}
        r15, r30, r1, r4 = (feats[tf].iloc[-1] for tf in ("M15", "M30", "H1", "H4"))
        regime, regime_h4 = classify(feats["M15"]), classify(feats["H4"])
        last_z = float(r15["ret_z"]) if r15["ret_z"] == r15["ret_z"] else 0.0
        vreg = volatility_regime(regime, last_z)

        # ---------------- Data Quality Firewall (blocking => UNAVAILABLE, never a trade)
        fw = FW.check_market(quote, bars, as_of, float(r15["atr"]) if r15["atr"] == r15["atr"] else None,
                             session not in ("CLOSED", "DAILY_BREAK"))
        audit["firewall"] = {"blocking": fw.blocking, "warnings": fw.warnings, "checks": fw.checks}
        if not fw.passed:
            return u("جدار جودة البيانات: " + fw.blocking[0], fw.blocking)

        # ---------------- multi-timeframe bias (direction only — never used as a probability)
        tf_votes = []
        for tf, row in (("H4", r4), ("H1", r1)):
            if abs(row["slope_ema50_atr"]) > 0.1:
                s = float(np.sign(row["slope_ema50_atr"]))
                tf_votes.append((s, f"ميل متوسط 50 على {tf} {'صاعد' if s > 0 else 'هابط'} (كفاءة الاتجاه {row['er20']:.2f})"))
        score = float(bias_score(r4["slope_ema50_atr"], r1["slope_ema50_atr"], r30["dist_ema20_atr"],
                                 r15["ret_16"], regime.vr))
        direction = int(bias_direction(score))
        support = [Evidence(engine="mtf_bias", weight=0.5, text_ar=t) for s, t in tf_votes if direction and s == direction]
        contrary = [Evidence(engine="mtf_bias", weight=-0.5, text_ar=t) for s, t in tf_votes if not (direction and s == direction)]

        missing = (list(context.missing) if context is not None else
                   ["بيانات الماكرو (FRED) غير متصلة", "تقويم الأحداث الاقتصادية غير متصل",
                    "تقارير COT غير متصلة", "خلاصات الأخبار الرسمية غير متصلة"])
        missing += ["إجماع التوقعات الاقتصادية غير متاح مجاناً (محركات Expectation Gap/Priced-In/Missing Reaction معطّلة)",
                    "عمق السوق وتدفق الأوامر المؤسسي غير متاح مجاناً (ولن يُدّعى)"]
        if mode == Mode.DEMO:
            missing.insert(0, "وضع تجريبي: الأسعار اصطناعية وليست سعر السوق")

        # ---------------- probabilistic path
        ps = self.paths.get(provider, as_of, bars)
        if ps.models is not None:
            pit.add("path_model_training_data", getattr(ps.models, "trained_until", None), P.PATH_VERSION)
        if context is not None:
            for k, v in context.macro.items():
                pit.add(f"FRED:{k}", v["published_at"], "FRED")
            if context.footprint:
                pit.add("CFTC:COT", context.footprint["published_at"], "CFTC")
            if context.etf_flows:
                pit.add("SPDR:GLD", pd.Timestamp(context.etf_flows["as_of_date"], tz="UTC") + pd.Timedelta(days=1, hours=2), "SPDR")
            for src, _, pub in context.recent_news:
                pit.add("news", pub, src)
        horizon_probs: dict = {}
        if ps.models is not None and direction != 0:
            row = M.build_feature_table(bars["M15"], bars["H1"], bars["H4"]).iloc[[-1]].copy()
            for c in M.DIRECTIONAL:
                row[c] = row[c] * direction
            row["dir"] = float(direction)
            if not row[M.FEATURES].isna().any(axis=None):
                horizon_probs = ps.models.predict(row)

        atr15 = float(r15["atr"])
        price = quote.price
        levels = compute_levels(direction, price, atr15) if direction else None
        inside = bool(levels and stop_inside_structure(direction, levels.stop_loss,
                                                         float(r15["swing_low_12"]), float(r15["swing_high_12"])))
        crit = review(direction, r15, r4, regime, session, inside, minutes_to_weekly_close(as_of))
        contrary.extend(crit.contrary)

        # ---------------- market trend (score, not probability) + support/resistance strength engine
        trend = market_trend({"M15": r15, "M30": r30, "H1": r1, "H4": r4}, vreg)
        sr = None
        try:
            lm = self.level_service.model((provider.meta.name, getattr(provider, "seed", None)), bars, as_of)
            sr = compute_sr(bars, as_of, price, lm)
        except Exception as exc:  # noqa: BLE001 — levels are optional context; failure never creates a trade
            missing.append(f"تعذّر حساب الدعوم والمقاومات: {str(exc)[:80]}")
        lvl_eff = LR.apply(direction, price, levels.stop_loss if levels else None, levels.tp1 if levels else None, sr) if sr else None
        if lvl_eff:
            crit.vetoes.extend(lvl_eff.vetoes)
            support.extend(lvl_eff.support)
            contrary.extend(lvl_eff.contrary)
        ref_close = bars["H1"][bars["H1"].index + pd.Timedelta(minutes=60) <= pd.Timestamp(as_of).normalize()]["close"]
        q_change = round(price - float(ref_close.iloc[-1]), 2) if len(ref_close) else None

        # ---------------- liquidity trap (price-shape inference)
        for ev_t in TRAP.scan(bars["M15"]):
            e = Evidence(engine="liquidity_trap", weight=0.3 if ev_t.implied_sign == direction else -0.3,
                         text_ar=f"{ev_t.text_ar} عند {ev_t.level:.2f} (قبل {ev_t.bars_ago} شمعة)")
            (support if direction and ev_t.implied_sign == direction else contrary).append(e)

        # ---------------- context: calendar / news embargo, COT, macro
        if context is not None:
            for name in context.embargo_events:
                crit.vetoes.append(f"حدث اقتصادي عالي التأثير خلال ±30 دقيقة: {name}")
            for src, title, _ in context.recent_news[:2]:
                crit.vetoes.append(f"خبر عالي التأثير قبل أقل من 30 دقيقة ({src}): {title[:80]}")
            fp = context.footprint
            if fp and direction:
                if fp["crowded"] == ("LONG" if direction > 0 else "SHORT"):
                    contrary.append(Evidence(engine="institutional_footprint", weight=-0.3, text_ar=(
                        f"مراكز المضاربين (Managed Money) مزدحمة في نفس الاتجاه — مئين {fp['percentile_3y']:.0%} "
                        f"(تقرير {fp['report_date']}، أسبوعي ومتأخر)")))
                elif fp["crowded"]:
                    support.append(Evidence(engine="institutional_footprint", weight=0.2, text_ar=(
                        f"مراكز المضاربين مزدحمة عكس الاتجاه — مجال لتغطية المراكز (COT {fp['report_date']})")))
            ry = context.macro.get("DFII10")
            if ry and direction and abs(ry["change_5obs"]) >= 0.10:
                rising = ry["change_5obs"] > 0
                txt = (f"العائد الحقيقي 10 سنوات {'ارتفع' if rising else 'انخفض'} {abs(ry['change_5obs']):.2f} نقطة "
                       f"في آخر 5 قراءات (FRED، يومي) — علاقة تاريخية عكسية مع الذهب، ليست قاعدة ثابتة")
                favourable = (not rising) if direction > 0 else rising
                (support if favourable else contrary).append(
                    Evidence(engine="macro", weight=0.2 if favourable else -0.2, text_ar=txt))
            fl = context.etf_flows
            if fl and direction and abs(fl["change_5d_z"]) >= 1.5:
                inflow = fl["change_5d"] > 0
                fav = inflow if direction > 0 else not inflow
                (support if fav else contrary).append(Evidence(engine="etf_flows", weight=0.2 if fav else -0.2, text_ar=(
                    f"صندوق GLD {'أضاف' if inflow else 'خفّض'} {abs(fl['change_5d']):.1f} طن في 5 أيام "
                    f"(z={fl['change_5d_z']:.1f}، يومي معلن، {fl['as_of_date']})")))
            gvz = context.macro.get("GVZCLS")
            if gvz and gvz["value"] and gvz["change_5obs"] / max(gvz["value"] - gvz["change_5obs"], 1e-6) >= 0.15:
                contrary.append(Evidence(engine="gvz", weight=-0.2, text_ar=(
                    f"مؤشر تقلب الذهب المتوقع GVZ ارتفع بقوة إلى {gvz['value']:.1f} — حركات أعنف وأقل قابلية للتنبؤ")))
            if any("تعارض" in w for w in getattr(quote, "warnings", [])):
                crit.vetoes.append("تعارض بين مصدري السعر — البيانات مشكوك فيها")

        # ---------------- historical analogs (descriptive)
        analog = None
        if direction and ps.ds is not None:
            qrow = M.build_feature_table(bars["M15"], bars["H1"], bars["H4"]).iloc[-1].copy()
            for c in M.DIRECTIONAL:
                qrow[c] = qrow[c] * direction
            if not qrow[[f for f in M.FEATURES if f != "dir"]].isna().any():
                analog = ANALOG.analogs(ps.ds, qrow, direction, as_of)
        if analog:
            nb = analog["neighbours"]
            txt = (f"أقرب {analog['k']} حالة تاريخية مشابهة: الهدف أولاً {nb['target_first']:.0%}، الوقف أولاً "
                   f"{nb['stop_first']:.0%} (وصفي، غير معاير" + ("، بيانات اصطناعية)" if mode == Mode.DEMO else ")"))
            good = nb["target_first"] > nb["stop_first"]
            (support if good else contrary).append(Evidence(engine="historical_analog", weight=0.2 if good else -0.2, text_ar=txt))

        p_main = horizon_probs.get(PRIMARY_HORIZON)
        # ---------------- V3 precision layer (only promoted rules / passed calibration ever act)
        pe, promoted, cal_ok = None, set(), False
        if self.precision is not None and direction and mode == Mode.LIVE:
            promoted, cal_ok = self.precision.promoted(), self.precision.calibration_ok()
            if promoted or cal_ok or self.shadow is not None:
                try:
                    pe = self.precision.evaluate_now(bars, ps.ds, as_of, direction)
                except Exception:  # noqa: BLE001 — a failing optional layer must never produce a trade
                    pe = None
                    if promoted:
                        crit.vetoes.append("تعذّر تشغيل طبقة الدقة المعتمدة — انتظار احترازي")
            for rule in sorted(promoted):
                if pe is None or not pe["accept"].get(rule, False):
                    crit.vetoes.append(f"رفضتها طبقة الدقة المعتمدة ({rule})")
        if cal_ok and pe is not None:
            p_main = np.array([pe["p_tp_cal"], pe["p_sl_cal"], pe["p_none_cal"]])
        if self.registry is not None and self.registry.safe_mode:
            crit.vetoes.append("وضع الأمان مفعّل بعد تدهور النموذج — لا إشارات حتى إعادة التحقق")
        ev = None
        if ps.qualified and p_main is not None and levels:
            ev = P.expected_net_return(float(p_main[0]), float(p_main[1]), levels.risk_per_oz,
                                       levels.risk_per_oz * levels.reward_risk_tp1, levels.cost_per_oz)

        # ---------------- uncertainty map (data / model / market kept separate)
        notes = []
        data_flags = (1 if mode == Mode.DEMO else 0) + (1 if len(missing) >= 4 else 0)
        if data_flags:
            notes.append("نقص مصادر بيانات أساسية")
        model_flags = 0 if ps.qualified else 2
        if not ps.qualified:
            notes.append("نموذج الاحتمالات غير مؤهل بعد")
        if ps.drift and ps.drift.alarm:
            model_flags += 1
            notes.append("إنذار انحراف (drift)")
        mkt_flags = {"LOW": 0, "NORMAL": 0, "HIGH": 1, "EXTREME": 2}[regime.vol] + \
            (1 if regime.bars_since_break == regime.bars_since_break and regime.bars_since_break < 4 else 0)
        if mkt_flags:
            notes.append("تقلب السوق أعلى من المعتاد أو تغيّر هيكلي حديث")
        lv = [_level(min(x, 2)) for x in (data_flags, model_flags, mkt_flags)]
        overall = "HIGH" if "HIGH" in lv else ("MEDIUM" if "MEDIUM" in lv else "LOW")
        n_missing_crit = 0 if mode == Mode.DEMO else sum(1 for m in missing if any(k in m for k in ("التقويم", "تقويم", "RSS")))
        budget = UB.compute(age, max_age, n_missing_crit + (1 if mode == Mode.DEMO else 0), len(fw.warnings), ps.qualified,
                            cal_ok, None, bool(ps.drift and ps.drift.alarm),
                            (analog["median_distance"] / analog["typical_distance"]) if analog and analog["typical_distance"] else None,
                            regime.vol_percentile, regime.bars_since_break,
                            pe.get("disagreement") if pe else None)
        notes += budget.notes_ar
        overall = "HIGH" if not budget.within else overall
        unc = Uncertainty(data=lv[0], model=lv[1], market=lv[2], overall=overall, notes_ar=notes,
                          budget_used=budget.used, budget_limit=budget.limit, budget_components=budget.components)

        # ---------------- duplicate protection
        dup = False
        if direction:
            last = self.store.last_by_signature("BUY" if direction > 0 else "SELL", mode.value)
            dup = bool(last and datetime.fromisoformat(last["valid_until_utc"]) > as_of)

        # ---------------- anti-trade gate
        cand = TradeCandidate(
            direction=direction, mode_live=(mode == Mode.LIVE), data_fresh=fresh, vol_regime=vreg,
            critic_vetoes=crit.vetoes, path_qualified=ps.qualified, path_reason_ar=ps.reason_ar,
            p_tp=None if p_main is None else float(p_main[0]), p_sl=None if p_main is None else float(p_main[1]),
            expected_net_return=ev, drift_alarm=bool(ps.drift and ps.drift.alarm),
            drift_reasons_ar=ps.drift.reasons_ar if ps.drift else [],
            news_calendar_connected=(self.config.news_calendar_connected or not self.config.require_news_calendar_live
                                     or bool(context and context.calendar_connected)),
            duplicate_active_signal=dup, uncertainty_level=overall)
        anti_reasons = anti_trade(cand)

        # ---------------- AI Decision Court: evidence + statistics + independent risk governor
        src = FW.check_sources(mode == Mode.LIVE, context)
        fw_all = FW.FirewallResult(blocking=fw.blocking + src.blocking, warnings=fw.warnings + src.warnings, checks=fw.checks)
        audit["firewall"] = {"blocking": fw_all.blocking, "warnings": fw_all.warnings, "checks": fw_all.checks}
        gov = GOV.review(direction, levels.risk_per_oz if levels else None, levels.reward_risk_tp1 if levels else None,
                         estimated_cost(), atr15, vreg, age, max_age, ledger_state(self.ledger, mode.value, as_of),
                         self.limits, as_of)
        pit_sum = pit.summary()
        audit["pit"] = pit_sum
        judgements = [COURT.statistical_judge(anti_reasons),
                      COURT.evidence_judge(fw_all, pit_sum, support, contrary),
                      COURT.risk_judge(gov)]
        approved, _ = COURT.rule(judgements)
        rejections = [] if approved else ([x for j in judgements for x in j.reasons_ar]
                                          or ["رفضت محكمة القرار الإشارة"])
        court = [CourtJudgement(judge=j.judge, passed=j.passed, reasons_ar=j.reasons_ar) for j in judgements]
        if self.shadow is not None and mode == Mode.LIVE and direction and levels and pe is not None:
            self.shadow.record(hashlib.sha256(f"{snap_hash}|shadow".encode()).hexdigest()[:16], as_of, direction, price,
                               levels.risk_per_oz, levels.reward_risk_tp1, PRIMARY_HORIZON,
                               {**pe["accept"], "production_court": bool(approved)})

        # ---------------- alternative (better) entry — structural; its fill probability is NOT estimated yet
        alt_price, alt_note = None, None
        if direction:
            ema20 = float(r15["ema20"])
            alt = min(price - 0.5 * atr15, ema20) if direction > 0 else max(price + 0.5 * atr15, ema20)
            if lvl_eff and lvl_eff.better_entry is not None:
                alt = lvl_eff.better_entry
                alt_note = "حافة أقرب منطقة " + ("دعم" if direction > 0 else "مقاومة") + " — دخول أفضل من السعر الحالي"
            else:
                alt_note = "مستوى ارتداد هيكلي أفضل للدخول"
            alt_price = round(crit.wait_for_price or alt, 2)
            cf = CF.compare(ps.fwd, direction, abs(price - alt_price) / atr15, 2.0, as_of) if ps.fwd is not None else None
            if cf:
                alt_note += (f"؛ تاريخياً وصله السعر خلال ساعة في {cf['fill_probability']:.0%} من الحالات، "
                             f"وابتعد السعر نحو الهدف دون العودة إليه في {cf['missed_move_probability']:.0%} "
                             f"(n={cf['n']}، تكرار غير معاير" + ("، بيانات اصطناعية)" if mode == Mode.DEMO else ")"))

        # ---------------- probabilities for display: LIVE + qualified only (schema also enforces it)
        rep = ps.models.reports.get(PRIMARY_HORIZON) if ps.models else None
        # numbers are shown only when the V3 calibration tests passed on LIVE data (and the path model qualified)
        show = (mode == Mode.LIVE and ps.qualified and cal_ok and pe is not None and rep is not None
                and rep.n_oos >= 300)
        hp = []
        if show:
            for h, pr in sorted(horizon_probs.items()):
                if h == PRIMARY_HORIZON:
                    pr = p_main  # calibrated
                r = ps.models.reports.get(h)
                hp.append(HorizonProbability(horizon_minutes=h, p_target_first=round(float(pr[0]), 4),
                                             p_stop_first=round(float(pr[1]), 4),
                                             p_neither=round(float(1 - pr[0] - pr[1]), 4),
                                             qualified=bool(r and r.qualified), oos_samples=r.n_oos if r else 0))
        reliability = None
        if rep is not None and rep.n_oos:
            reliability = (f"Brier متعدد الفئات {rep.brier_model:.4f} مقابل {rep.brier_climatology:.4f} للتكرار التاريخي؛ "
                           f"أكبر فجوة معايرة {rep.max_reliability_gap:.3f}؛ {rep.n_oos} عينة خارج العينة"
                           + (" (بيانات اصطناعية)" if mode == Mode.DEMO else ""))

        common = dict(
            mode=mode, spot_or_proxy=spot, provider=provider.meta.name, quote=price,
            quote_timestamp_utc=quote.observed_at, analyzed_at_utc=as_of, model_version=P.PATH_VERSION,
            market_regime=f"M15: {regime.label_ar} | H4: {regime_h4.label_ar}", vol_regime=vreg,
            data_freshness=fr, data_quality="DEGRADED" if mode == Mode.DEMO else "GOOD", missing_data=missing,
            supporting_evidence=support, contrary_evidence=contrary, snapshot_hash=snap_hash,
            estimated_cost=round(estimated_cost(), 2), uncertainty=unc,
            probability_method=(f"{P.PATH_VERSION}: multinomial logit, purged walk-forward vs climatology"
                                + ("; calibrated (isotonic/Platt OvR) on the latest window" if show else "")),
            probability_reliability_ar=reliability,
            calibration_sample_count=rep.n_oos if (show and rep) else 0,
            alternative_entry_price=alt_price, alternative_entry_note_ar=alt_note, court=court,
            engines_used=ENGINES_ACTIVE + ["market_trend", "support_resistance"] + (CONTEXT_ENGINES if context is not None else []),
            market_trend=trend, quote_change=q_change,
            quote_change_pct=round(100 * q_change / (price - q_change), 3) if q_change is not None and price != q_change else None,
            levels=None if sr is None else {
                "supports": sr["supports"], "resistances": sr["resistances"], "validated": sr["validated"],
                "atr_h1": sr["atr_h1"], "method_note_ar": sr["method_note_ar"],
                "validation_ar": sr["validation"].get("reason_ar")},
            reevaluate_ar=(lvl_eff.reevaluate_ar if lvl_eff else []),
            expected_net_return=round(ev, 2) if (show and ev is not None) else None)
        if show:
            common.update(probability_target_before_stop=round(float(p_main[0]), 4),
                          probability_stop_before_target=round(float(p_main[1]), 4),
                          probability_neither=round(float(1 - p_main[0] - p_main[1]), 4),
                          probabilities_by_horizon=hp)
        did = hashlib.sha256(f"{snap_hash}|{mode.value}|{P.PATH_VERSION}".encode()).hexdigest()[:16]

        if rejections:
            short = _reason(trend, sr, direction, rejections[0])
            d = Decision(decision_id=did, action=Action.WAIT, reason_short_ar=short,
                         wait_for_ar=crit.wait_for_ar or "انتظر حتى تزول أسباب الرفض أو يصل السعر إلى المستوى البديل",
                         wait_for_price=alt_price, warning_ar="قرار مكرر" if dup else None, **common)
            return self._finish(d, audit)

        act = Action.BUY if direction > 0 else Action.SELL
        side_ar = "شراء" if direction > 0 else "بيع"
        short = _reason(trend, sr, direction, None)
        inval = [f"إغلاق شمعة M15 {'تحت' if direction > 0 else 'فوق'} {levels.stop_loss:.2f}",
                 f"انقلاب ميل H1 ضد {side_ar}", "صدور خبر اقتصادي عالي التأثير قبل الدخول",
                 "انتهاء صلاحية الإشارة دون دخول ضمن النطاق"]
        d = Decision(decision_id=did, action=act, entry_min=levels.entry_min, entry_max=levels.entry_max,
                     stop_loss=levels.stop_loss, tp1=levels.tp1, tp2=levels.tp2, tp3=levels.tp3,
                     horizon_minutes=PRIMARY_HORIZON, valid_until_utc=as_of + SIGNAL_VALIDITY,
                     reward_risk=levels.reward_risk_tp1, invalidation_ar=inval, reason_short_ar=short,
                     warning_ar="إشارة بحثية للتداول الورقي فقط — ليست نصيحة استثمارية ولا تُنفَّذ تلقائياً",
                     **common)
        return self._finish(d, audit)

    def _finish(self, d: Decision, audit: dict | None = None) -> Decision:
        record = {"decision": d.model_dump(mode="json"), "pit": (audit or {}).get("pit"),
                  "firewall": (audit or {}).get("firewall"),
                  "versions": {"schema": SCHEMA_VERSION, "path_model": P.PATH_VERSION, "baseline_model": M.MODEL_VERSION},
                  "governor_limits": {k: str(v) for k, v in self.limits.__dict__.items()},
                  "promoted_precision_rules": sorted(self.precision.promoted()) if self.precision else []}
        d.audit_hash = self.store.append_audit(d.decision_id, d.analyzed_at_utc.isoformat(), record)
        self.store.save_decision(d)
        return d
