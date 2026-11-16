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
from . import outlook as OL
from .msg import M as Mg, cut_short, ref_dict as _ref_dict
from .levels import LevelService, compute_levels as compute_sr
from .trend import market_trend
from .features import frame_features, session_of
from . import data_quality as DQ
from .providers.base import MarketDataProvider, Quote
from .regime import VOL_REGIME_AR, classify, volatility_regime
from .risk import compute_levels, estimated_cost, stop_inside_structure
from .schemas import (Action, CourtJudgement, DataFreshness, Decision, Evidence, HorizonOutlook, HorizonProbability, Mode,
                      LevelsBlock, MarketTrend, PriceLevel, ReasonRef, SCHEMA_VERSION, SpotOrProxy, Uncertainty,
                      DataHealth, DQCheck)
from .store import Store

MIN_BARS = {"M15": 600, "M30": 300, "H1": 200, "H4": 100}
FETCH_BARS = {"M15": 20000, "M30": 10000, "H1": 5000, "H4": 1500}
DAILY_BARS = 6000  # ~23 years of daily bars (Twelve Data: one call of outputsize 5000)
MAX_QUOTE_AGE_S = {Mode.DEMO: 180.0, Mode.LIVE: 180.0}
SIGNAL_VALIDITY = timedelta(minutes=15)
PRIMARY_HORIZON = 240
DRIFT_FEATURES = ["er20", "vr4", "vol_ratio", "range_z", "h1_er20", "h4_er20", "log_since_break"]
ENGINES_ACTIVE = ["data_quality", "volatility_regime", "mtf_bias", "probabilistic_path", "adversarial_critic",
                  "liquidity_trap", "structural_break(CUSUM)", "model_drift_sentinel", "uncertainty_map",
                  "historical_analog", "counterfactual", "anti_trade", "risk", "daily_trend_filter",
                  "multi_horizon_outlook"]
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


def _reason(trend: dict, sr: dict | None, direction: int, blocker: str | None):
    """Exactly two short sentences: market context, then the deciding factor."""
    h4 = trend.get("per_timeframe", {}).get("H4", "محايد")
    h4w = {"صاعد": "w.up", "هابط": "w.down", "محايد": "w.neutral"}.get(h4)
    tail = Mg("w.none")
    if sr:
        s1 = sr["supports"][0] if sr["supports"] else None
        r1 = sr["resistances"][0] if sr["resistances"] else None
        if direction > 0 and s1:
            tail = Mg("rs.tail_above", f"{s1['price']:.2f}")
        elif direction < 0 and r1:
            tail = Mg("rs.tail_below", f"{r1['price']:.2f}")
        elif s1 and r1:
            tail = Mg("rs.tail_between", f"{s1['price']:.2f}", f"{r1['price']:.2f}")
    lbl = {"صاعد": "w.up", "هابط": "w.down", "عرضي": "w.sideways"}.get(trend["label_ar"])
    first = Mg("rs.ctx", Mg(h4w) if h4w else h4, Mg(lbl) if lbl else trend["label_ar"], tail)
    if blocker is None:
        second = Mg("rs.ok")
    else:
        from .msg import Msg
        if isinstance(blocker, Msg):
            second = Mg("rs.wait", blocker)
        else:
            second = Mg("rs.wait", cut_short(blocker))
    return Mg("rs.short", first, second)


def _ref(x):
    return None if x is None else ReasonRef(**_ref_dict(x))


def _refs(xs):
    return [r for r in (_ref(x) for x in (xs or [])) if r is not None]


def daily_outlooks(daily, as_of: datetime, mode: Mode, context: Optional[MarketContext]) -> list:
    """WEEK / MONTH cards from the fixed daily rules (see outlook.py). Hit rates only for validated LIVE rules."""
    views = OL.compute(daily, as_of, synthetic=(mode == Mode.DEMO),
                       upcoming_events=list(context.upcoming_events) if context is not None else None,
                       macro=context.macro if context is not None else None)
    out = []
    for v in views:
        show = v.validated and mode == Mode.LIVE and v.stats.hit_rate is not None
        method = Mg("mt.daily", OL.OUTLOOK_VERSION, Mg(f"ru.{v.horizon.lower()}"), f"{OL.ROUND_TRIP_COST:.2%}")
        lv = None
        if v.levels:
            lv = LevelsBlock(supports=[PriceLevel(**z) for z in v.levels["supports"]],
                             resistances=[PriceLevel(**z) for z in v.levels["resistances"]],
                             validated=False, method_note_ar=str(v.levels["method_ref"]))
        out.append(HorizonOutlook(
            horizon=v.horizon, label_ar=OL.LABEL_AR[v.horizon], action=Action(v.action), tilt=v.tilt,
            stance_ar=v.stance_ar, reason_ar=v.reason_ar, validated=v.validated, validation_ar=v.validation_ar,
            hit_rate=v.stats.hit_rate if show else None, base_rate=v.stats.base_rate if show else None,
            samples=v.stats.n, horizon_days=OL.HORIZON_DAYS[v.horizon], entry_price=v.entry_price,
            stop_loss=v.stop_loss, target=v.target, wait_for_price=v.wait_for_price,
            method_ar=str(method), warnings_ar=[str(w) for w in v.warnings_ar],
            stance_ref=_ref(v.stance_msg), reason_ref=_ref(v.reason_msg), validation_ref=_ref(v.validation_msg),
            method_ref=_ref(method), warnings_ref=_refs(v.warnings_ar), facts_ref=_refs(v.facts),
            levels=lv, trend=MarketTrend(**v.trend) if v.trend else None))
    return out


def hours_card(action: Action, reason: Optional[str], qualified: bool, direction: int,
               wait_for_price: Optional[float]) -> HorizonOutlook:
    """HOURS mirrors the main intraday decision (its levels and probabilities live on the Decision itself)."""
    stance = Mg({Action.BUY: "st.buy", Action.SELL: "st.sell", Action.WAIT: "st.wait", Action.UNAVAILABLE: "st.na"}[action])
    if action == Action.WAIT and direction:
        stance = Mg("st.wait_lean_buy" if direction > 0 else "st.wait_lean_sell")
    val = None if qualified else Mg("va.hours_unq")
    method = Mg("mt.hours")
    return HorizonOutlook(horizon="HOURS", label_ar=OL.LABEL_AR["HOURS"], action=action,
                          tilt=direction if action != Action.UNAVAILABLE else 0, stance_ar=str(stance),
                          reason_ar=reason or "", validated=qualified,
                          validation_ar=None if val is None else str(val),
                          wait_for_price=wait_for_price if action == Action.WAIT else None,
                          method_ar=str(method), stance_ref=_ref(stance),
                          reason_ref=_ref(reason) if reason else None, validation_ref=_ref(val), method_ref=_ref(method),
                          probabilities_available=qualified and action in (Action.BUY, Action.SELL))


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
                        data_quality="INSUFFICIENT", warning_ar=str(reason_ar), reason_short_ar=str(reason_ar),
                        reason_short_ref=_ref(reason_ar), warning_ref=_ref(reason_ar), missing_refs=_refs(missing),
                        missing_data=[str(x) for x in (missing or [])], snapshot_hash=snap_hash, engines_used=["data_quality"])

    def _last_session_context(self, d: Decision, provider, bars: dict, counts: dict, as_of: datetime, quote) -> None:
        """Market closed: keep the LAST session's trend and levels visible for planning. Context only — the
        decision stays UNAVAILABLE and nothing here can create a trade."""
        d.market_closed = True
        if quote is None or not all(counts.get(tf, 0) >= n for tf, n in MIN_BARS.items()):
            return
        try:
            fe = {tf: frame_features(df).iloc[-1] for tf, df in bars.items() if tf in ("M15", "M30", "H1", "H4")}
            d.market_trend = MarketTrend(**market_trend(fe, "RANGE"))
            lm = self.level_service.model((provider.meta.name, getattr(provider, "seed", None)), bars, as_of)
            sr = compute_sr(bars, as_of, quote.price, lm)
            d.levels = LevelsBlock(supports=sr["supports"], resistances=sr["resistances"], validated=sr["validated"],
                                   atr_h1=sr["atr_h1"], method_note_ar=sr["method_note_ar"],
                                   validation_ar=sr["validation"].get("reason_ar"))
        except Exception:  # noqa: BLE001 — optional context
            pass

    def decide(self, provider: Optional[MarketDataProvider], mode: Mode, as_of: datetime, *args, **kwargs) -> Decision:
        """The decision plus one trade plan per horizon (plans only re-express the decision; see plans.py)."""
        self._daily, self._ctx, self._dq, self._bars = None, None, None, None
        return self._decide(provider, mode, as_of, *args, **kwargs)

    def _decide(self, provider: Optional[MarketDataProvider], mode: Mode, as_of: datetime,
               context: Optional[MarketContext] = None) -> Decision:
        self._ctx = context
        max_age = MAX_QUOTE_AGE_S[mode]
        if provider is None:
            fr = DataFreshness(max_allowed_seconds=max_age, is_fresh=False)
            return self._finish(self._unavailable(
                mode, None, as_of, Mg("un.no_provider"),
                fr, missing=[Mg("md.no_provider")]))
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
        if quote is None and session_of(pd.Timestamp(as_of)) == "CLOSED" and len(bars.get("M15", [])):
            # weekend: no live print is a market price; the last session's close (at its real time) is the price
            last = bars["M15"].index[-1]
            quote = Quote(price=round(float(bars["M15"]["close"].iloc[-1]), 2),
                          observed_at=(last + pd.Timedelta(minutes=15)).to_pydatetime(), fetched_at=as_of,
                          provider=provider.meta.name)
            age = quote.age_seconds(as_of)
        daily = None
        try:
            db = provider.bars("D1", as_of, DAILY_BARS)
            if db is not None:
                db.validate()
                daily = db.df
        except Exception:  # noqa: BLE001 — daily history is optional context; never blocks or creates a trade
            daily = None
        self._daily = daily
        self._bars = bars
        try:
            outlooks = daily_outlooks(daily, as_of, mode, context)
        except Exception:  # noqa: BLE001 — optional layer
            outlooks = []
        fresh = quote is not None and age is not None and 0 <= age <= max_age
        fr = DataFreshness(quote_age_seconds=age, max_allowed_seconds=max_age, is_fresh=fresh, bars_available=counts)
        snap_hash, snap = _snapshot(provider, mode, as_of, quote, bars)
        self.store.save_snapshot(snap_hash, as_of.isoformat(), snap)
        spot = SpotOrProxy(provider.meta.spot_or_proxy)
        session = session_of(pd.Timestamp(as_of))
        try:  # automatic data-quality gate on the bars this decision would use
            self._dq = DQ.decision_gate(bars, as_of, session not in ("CLOSED", "DAILY_BREAK"))
        except Exception:  # noqa: BLE001 — a failing check must never crash the engine; report it as unknown
            self._dq = {"status": "WARN", "checks": []}

        pit = PITLedger(as_of)
        if quote is not None:
            pit.add("quote", quote.observed_at, provider.meta.name)
        for tf_, df_ in bars.items():
            pit.add(f"last_closed_{tf_}_bar", df_.index[-1] + pd.Timedelta(minutes={"M15": 15, "M30": 30, "H1": 60, "H4": 240}[tf_]),
                    provider.meta.name)
        audit = {"pit": None, "firewall": None}

        def u(msg, missing=None, closed=False):
            audit["pit"] = pit.summary()
            d_u = self._unavailable(mode, provider, as_of, msg, fr, quote, missing=missing, snap_hash=snap_hash, spot=spot)
            d_u.outlooks = [hours_card(Action.UNAVAILABLE, msg, False, 0, None)] + outlooks
            if closed:
                self._last_session_context(d_u, provider, bars, counts, as_of, quote)
            return self._finish(d_u, audit)
        if corrupt:
            return u(Mg("un.corrupt"), corrupt)
        if quote is None:
            return u(Mg("un.no_quote"))
        if session == "CLOSED":
            return u(Mg("un.closed"), closed=True)
        if self._dq.get("status") == "FAIL":
            bad = ", ".join(sorted({c["code"] for c in self._dq["checks"] if c["status"] == "FAIL"}))
            return u(Mg("un.dq_fail", bad))
        if not fresh:
            return u(Mg("un.stale", f"{age:.0f}"))
        short = [tf for tf, n in MIN_BARS.items() if counts.get(tf, 0) < n]
        if short:
            return u(Mg("un.insufficient"), [f"شموع {tf}" for tf in short])

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
            return u(Mg("un.firewall", fw.blocking[0]), fw.blocking)

        # ---------------- multi-timeframe bias (direction only — never used as a probability)
        tf_votes = []
        for tf, row in (("H4", r4), ("H1", r1)):
            if abs(row["slope_ema50_atr"]) > 0.1:
                s = float(np.sign(row["slope_ema50_atr"]))
                tf_votes.append((s, Mg("ev.mtf_slope", tf, Mg("w.up") if s > 0 else Mg("w.down"), f"{row['er20']:.2f}")))
        score = float(bias_score(r4["slope_ema50_atr"], r1["slope_ema50_atr"], r30["dist_ema20_atr"],
                                 r15["ret_16"], regime.vr))
        direction = int(bias_direction(score))
        support = [Evidence(engine="mtf_bias", weight=0.5, text_ar=t) for s, t in tf_votes if direction and s == direction]
        contrary = [Evidence(engine="mtf_bias", weight=-0.5, text_ar=t) for s, t in tf_votes if not (direction and s == direction)]

        missing = (list(context.missing) if context is not None else
                   [Mg("md.macro"), Mg("md.calendar"), Mg("md.cot"), Mg("md.news_feeds")])
        missing += [Mg("md.no_consensus"), Mg("md.no_depth")]
        if mode == Mode.DEMO:
            missing.insert(0, Mg("md.demo"))

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
        d_trend = OL.daily_trend(daily, as_of)
        if direction and d_trend and d_trend != direction:
            crit.vetoes.append(Mg("ve.daily_trend"))
        elif direction and d_trend == direction:
            support.append(Evidence(engine="daily_trend_filter", weight=0.3,
                                    text_ar=Mg("ev.daily_ok")))

        # ---------------- market trend (score, not probability) + support/resistance strength engine
        trend = market_trend({"M15": r15, "M30": r30, "H1": r1, "H4": r4}, vreg)
        sr = None
        try:
            lm = self.level_service.model((provider.meta.name, getattr(provider, "seed", None)), bars, as_of)
            sr = compute_sr(bars, as_of, price, lm)
        except Exception as exc:  # noqa: BLE001 — levels are optional context; failure never creates a trade
            missing.append(Mg("md.levels_failed", str(exc)[:80]))
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
                         text_ar=Mg("ev.trap", ev_t.text_ar, f"{ev_t.level:.2f}", ev_t.bars_ago))
            (support if direction and ev_t.implied_sign == direction else contrary).append(e)

        # ---------------- context: calendar / news embargo, COT, macro
        if context is not None:
            for name in context.embargo_events:
                crit.vetoes.append(Mg("ve.calendar", name))
            for src, title, _ in context.recent_news[:2]:
                crit.vetoes.append(Mg("ve.news", src, title[:80]))
            fp = context.footprint
            if fp and direction:
                if fp["crowded"] == ("LONG" if direction > 0 else "SHORT"):
                    contrary.append(Evidence(engine="institutional_footprint", weight=-0.3, text_ar=Mg("ev.cot_same", f"{fp['percentile_3y']:.0%}", fp['report_date'])))
                elif fp["crowded"]:
                    support.append(Evidence(engine="institutional_footprint", weight=0.2, text_ar=Mg("ev.cot_opp", fp['report_date'])))
            ry = context.macro.get("DFII10")
            if ry and direction and abs(ry["change_5obs"]) >= 0.10:
                rising = ry["change_5obs"] > 0
                txt = Mg("ev.real_yield", Mg("w.rose") if rising else Mg("w.fell"), f"{abs(ry['change_5obs']):.2f}")
                favourable = (not rising) if direction > 0 else rising
                (support if favourable else contrary).append(
                    Evidence(engine="macro", weight=0.2 if favourable else -0.2, text_ar=txt))
            fl = context.etf_flows
            if fl and direction and abs(fl["change_5d_z"]) >= 1.5:
                inflow = fl["change_5d"] > 0
                fav = inflow if direction > 0 else not inflow
                (support if fav else contrary).append(Evidence(engine="etf_flows", weight=0.2 if fav else -0.2, text_ar=Mg("ev.etf", Mg("w.added") if inflow else Mg("w.cut"), f"{abs(fl['change_5d']):.1f}",
                                                                                 f"{fl['change_5d_z']:.1f}", fl['as_of_date'])))
            gvz = context.macro.get("GVZCLS")
            if gvz and gvz["value"] and gvz["change_5obs"] / max(gvz["value"] - gvz["change_5obs"], 1e-6) >= 0.15:
                contrary.append(Evidence(engine="gvz", weight=-0.2, text_ar=Mg("ev.gvz", f"{gvz['value']:.1f}")))
            if any("تعارض" in w for w in getattr(quote, "warnings", [])):
                crit.vetoes.append(Mg("ve.price_conflict"))

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
            txt = Mg("ev.analog", analog['k'], f"{nb['target_first']:.0%}", f"{nb['stop_first']:.0%}",
                     Mg("w.syn_tail") if mode == Mode.DEMO else Mg("w.none"))
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
                        crit.vetoes.append(Mg("ve.precision_failed"))
            for rule in sorted(promoted):
                if pe is None or not pe["accept"].get(rule, False):
                    crit.vetoes.append(Mg("ve.precision_reject", rule))
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
                alt_note = Mg("alt.edge", Mg("w.support") if direction > 0 else Mg("w.resistance"))
            else:
                alt_note = Mg("alt.structural")
            alt_price = round(crit.wait_for_price or alt, 2)
            cf = CF.compare(ps.fwd, direction, abs(price - alt_price) / atr15, 2.0, as_of) if ps.fwd is not None else None
            if cf:
                alt_note = Mg("alt.note", alt_note, Mg("alt.fill", f"{cf['fill_probability']:.0%}",
                                                      f"{cf['missed_move_probability']:.0%}", cf['n'],
                                                      Mg("w.syn_tail") if mode == Mode.DEMO else Mg("w.none")))

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
            alternative_entry_price=alt_price, alternative_entry_note_ar=None if alt_note is None else str(alt_note),
            alternative_entry_note_ref=_ref(alt_note), court=court,
            engines_used=ENGINES_ACTIVE + ["market_trend", "support_resistance"] + (CONTEXT_ENGINES if context is not None else []),
            market_trend=trend, quote_change=q_change,
            quote_change_pct=round(100 * q_change / (price - q_change), 3) if q_change is not None and price != q_change else None,
            levels=None if sr is None else {
                "supports": sr["supports"], "resistances": sr["resistances"], "validated": sr["validated"],
                "atr_h1": sr["atr_h1"], "method_note_ar": sr["method_note_ar"],
                "validation_ar": sr["validation"].get("reason_ar")},
            reevaluate_ar=(lvl_eff.reevaluate_ar if lvl_eff else []),
            reevaluate_refs=_refs(lvl_eff.reevaluate_ar if lvl_eff else []),
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
                         wait_for_ar=crit.wait_for_ar or Mg("wf.default"), wait_for_ref=_ref(crit.wait_for_ar or Mg("wf.default")),
                         reason_short_ref=_ref(short), warning_ref=_ref(Mg("wn.duplicate")) if dup else None,
                         missing_refs=_refs(missing),
                         wait_for_price=alt_price, warning_ar=str(Mg("wn.duplicate")) if dup else None,
                         outlooks=[hours_card(Action.WAIT, short, ps.qualified, direction, alt_price)] + outlooks,
                         **common)
            return self._finish(d, audit)

        act = Action.BUY if direction > 0 else Action.SELL
        side_ar = "شراء" if direction > 0 else "بيع"
        short = _reason(trend, sr, direction, None)
        inval = [Mg("iv.candle", Mg("w.below") if direction > 0 else Mg("w.above"), f"{levels.stop_loss:.2f}"),
                 Mg("iv.slope", Mg("w.buying") if direction > 0 else Mg("w.selling")), Mg("iv.news"), Mg("iv.expired")]
        d = Decision(decision_id=did, action=act, entry_min=levels.entry_min, entry_max=levels.entry_max,
                     stop_loss=levels.stop_loss, tp1=levels.tp1, tp2=levels.tp2, tp3=levels.tp3,
                     horizon_minutes=PRIMARY_HORIZON, valid_until_utc=as_of + SIGNAL_VALIDITY,
                     reward_risk=levels.reward_risk_tp1, invalidation_ar=inval, reason_short_ar=short,
                     warning_ar=str(Mg("wn.paper")), warning_ref=_ref(Mg("wn.paper")), reason_short_ref=_ref(short),
                     invalidation_refs=_refs(inval), missing_refs=_refs(missing),
                     outlooks=[hours_card(act, short, ps.qualified, direction, None)] + outlooks,
                     **common)
        return self._finish(d, audit)

    def _finish(self, d: Decision, audit: dict | None = None) -> Decision:
        from . import plans as PL
        dq = getattr(self, "_dq", None)
        if dq and d.data_health is None:
            d.data_health = DataHealth(status=dq["status"], checks=[DQCheck(**c) for c in dq["checks"]])
        ctx = getattr(self, "_ctx", None)
        try:  # v1.14: when each input was last updated (an old analysis is never shown as live)
            from . import source_status as SS
            d.sources = SS.build(d.analyzed_at_utc, d.quote_timestamp_utc, getattr(self, "_bars", None),
                                 getattr(self, "_daily", None), ctx, gold_hours=True,
                                 market_closed=bool(d.market_closed))
        except Exception:  # noqa: BLE001 — informative only
            pass
        PL.attach(d, getattr(self, "planners", None), getattr(self, "_daily", None),
                  getattr(ctx, "macro_frames", None) or None)  # plans are part of the audit
        from . import brief as BR
        from . import checklist as CK
        try:
            CK.attach(d, getattr(self, "_ctx", None))
        except Exception:  # noqa: BLE001 — context only
            pass
        try:
            d.daily_brief = BR.build(d)
            h1 = (getattr(self, "_bars", None) or {}).get("H1")
            if d.daily_brief is not None and not d.market_closed:
                d.daily_brief.events = BR.events(d, h1)
        except Exception:  # noqa: BLE001 — context only
            d.daily_brief = None
        record = {"decision": d.model_dump(mode="json"), "pit": (audit or {}).get("pit"),
                  "firewall": (audit or {}).get("firewall"),
                  "versions": {"schema": SCHEMA_VERSION, "path_model": P.PATH_VERSION, "baseline_model": M.MODEL_VERSION},
                  "governor_limits": {k: str(v) for k, v in self.limits.__dict__.items()},
                  "promoted_precision_rules": sorted(self.precision.promoted()) if self.precision else []}
        d.audit_hash = self.store.append_audit(d.decision_id, d.analyzed_at_utc.isoformat(), record)
        self.store.save_decision(d)
        return d
