"""Typed signal contract shared with the Android app (schema/decision.schema.json is generated from this)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.13.0"


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"
    UNAVAILABLE = "UNAVAILABLE"


class Mode(str, Enum):
    DEMO = "DEMO"
    LIVE = "LIVE"


class SpotOrProxy(str, Enum):
    SPOT = "SPOT"
    PROXY = "PROXY"
    SYNTHETIC = "SYNTHETIC"
    NONE = "NONE"


class ReasonRef(BaseModel):
    """A translatable sentence: `code` + ordered `args` (strings or nested refs). `text_ar` is the Arabic rendering
    and the fallback for any code the client has no string for (code 'raw' = show text_ar as is)."""
    model_config = ConfigDict(extra="forbid")
    code: str
    args: list[Any] = Field(default_factory=list)
    text_ar: str


def _ref_of(x: Any) -> Optional[dict]:
    from .msg import Msg, ref_dict
    return ref_dict(x) if isinstance(x, Msg) else None


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: str
    text_ar: str
    weight: float = Field(ge=-1.0, le=1.0)
    text_ref: Optional[ReasonRef] = None

    @model_validator(mode="before")
    @classmethod
    def _capture_ref(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("text_ref") is None:
            r = _ref_of(data.get("text_ar"))
            if r is not None:
                data = {**data, "text_ar": str(data["text_ar"]), "text_ref": r}
        return data


class DataFreshness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_age_seconds: Optional[float] = None
    max_allowed_seconds: float
    is_fresh: bool
    bars_available: dict[str, int] = Field(default_factory=dict)


class HorizonProbability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    horizon_minutes: int
    p_target_first: float = Field(ge=0.0, le=1.0)
    p_stop_first: float = Field(ge=0.0, le=1.0)
    p_neither: float = Field(ge=0.0, le=1.0)
    qualified: bool
    oos_samples: int


class Uncertainty(BaseModel):
    """V2 #16: separates uncertainty sources instead of one opaque 'confidence'."""
    model_config = ConfigDict(extra="forbid")
    data: str  # LOW | MEDIUM | HIGH
    model: str
    market: str
    overall: str
    notes_ar: list[str] = Field(default_factory=list)
    budget_used: Optional[float] = None  # V4 Uncertainty Budget
    budget_limit: Optional[float] = None
    budget_components: dict[str, float] = Field(default_factory=dict)


class CourtJudgement(BaseModel):
    """V4 AI Decision Court: one independent judge's ruling."""
    model_config = ConfigDict(extra="forbid")
    judge: str  # evidence | statistics | risk_governor
    passed: bool
    reasons_ar: list[str] = Field(default_factory=list)
    reasons_ref: list[ReasonRef] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _capture_refs(cls, data: Any) -> Any:
        from .msg import ref_dict
        if isinstance(data, dict) and not data.get("reasons_ref") and data.get("reasons_ar"):
            data = {**data, "reasons_ref": [ref_dict(x) for x in data["reasons_ar"]],
                    "reasons_ar": [str(x) for x in data["reasons_ar"]]}
        return data


class MarketTrend(BaseModel):
    """Analytical trend score (0-100) — NOT a probability."""
    model_config = ConfigDict(extra="forbid")
    direction: str  # UP | DOWN | SIDEWAYS | UNKNOWN
    strength: Optional[int] = Field(default=None, ge=0, le=100)
    label_ar: str
    agreement: Optional[float] = None
    per_timeframe: dict[str, str] = Field(default_factory=dict)
    note_ar: Optional[str] = None


class PriceLevel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str  # S1..S3 / R1..R3 (ordered by distance)
    price: float
    zone_low: float
    zone_high: float
    strength: Optional[int] = Field(default=None, ge=0, le=100)  # percentile rank, only when validated
    strength_label_ar: str
    tests: int
    timeframes: list[str] = Field(default_factory=list)
    role_flip: bool = False
    broken_recently: bool = False
    distance_atr: float
    last_test_utc: Optional[str] = None
    # v1.11: if the price reaches this zone, P(it holds) within 12 H1 bars — only when calibrated out of sample
    hold_probability: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class LevelsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supports: list[PriceLevel] = Field(default_factory=list)
    resistances: list[PriceLevel] = Field(default_factory=list)
    validated: bool
    atr_h1: Optional[float] = None
    validation_ar: Optional[str] = None
    method_note_ar: Optional[str] = None

    @model_validator(mode="after")
    def _no_unvalidated_numbers(self) -> "LevelsBlock":
        if not self.validated and any(z.strength is not None for z in self.supports + self.resistances):
            raise ValueError("numeric level strength requires out-of-sample validation")
        return self


class Setup(str, Enum):
    BUY_NOW = "BUY_NOW"
    SELL_NOW = "SELL_NOW"
    WAIT_TO_BUY = "WAIT_TO_BUY"
    WAIT_TO_SELL = "WAIT_TO_SELL"
    WAIT = "WAIT"
    UNAVAILABLE = "UNAVAILABLE"


class TradePlan(BaseModel):
    """What the user can act on for ONE horizon (v1.7).

    recommendation=True only for a LIVE, validated *_NOW plan. WAIT_TO_* is a WATCH level (where a setup would be
    looked for), never a recommendation: it carries no stop or target, so it cannot be mistaken for a trade."""
    model_config = ConfigDict(extra="forbid")
    setup: Setup
    recommendation: bool = False
    side: Optional[str] = None  # BUY | SELL
    order: Optional[str] = None  # MARKET (enter in the zone now) | LIMIT
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    watch_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    reward_risk: Optional[float] = None
    expected_minutes: Optional[int] = None
    expected_days: Optional[int] = None
    valid_until_utc: Optional[datetime] = None
    invalidation_refs: list[ReasonRef] = Field(default_factory=list)
    # planner output (v1.7.1): shown only for a qualified recommendation; probabilities only when calibrated
    method: Optional[str] = None  # RULE | PLANNER
    expected_net_return_pct: Optional[float] = None
    p_target_first: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    p_stop_first: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    p_timeout: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    p_fill: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    median_days_to_target: Optional[float] = None
    fill_days: Optional[int] = None

    @model_validator(mode="after")
    def _consistent(self) -> "TradePlan":
        now = self.setup in (Setup.BUY_NOW, Setup.SELL_NOW)
        cond = self.setup in (Setup.WAIT_TO_BUY, Setup.WAIT_TO_SELL)
        if self.recommendation and not (now or cond):
            raise ValueError("only a trade or a conditional entry can be a recommendation")
        if (now or (cond and self.recommendation)) and (self.entry_low is None or self.stop_loss is None or self.target is None):
            raise ValueError("a recommended plan needs entry, stop and target")
        if not now and not self.recommendation and (self.stop_loss is not None or self.target is not None):
            raise ValueError("a watch / wait plan must not carry a stop or a target")
        if cond and self.watch_price is None:
            raise ValueError("WAIT_TO_* needs its watch price")
        if not self.recommendation and any(v is not None for v in (self.p_target_first, self.p_stop_first, self.p_timeout,
                                                                   self.p_fill, self.expected_net_return_pct)):
            raise ValueError("probabilities / expected return only for a qualified recommendation")
        return self


class PerfStats(BaseModel):
    """Track record of one horizon from one source. Pending / never-filled signals are NOT counted as trades."""
    model_config = ConfigDict(extra="forbid")
    source: str  # OOS_BACKTEST | OOS_PLANNER | LIVE_FORWARD | LIVE_PAPER
    unit: str  # USD_OZ | PCT
    trades: int = Field(default=0, ge=0)
    hits: int = Field(default=0, ge=0)  # target before stop (HOURS) / right direction after costs (WEEK, MONTH)
    pending: int = Field(default=0, ge=0)
    not_filled: int = Field(default=0, ge=0)
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    expectancy: Optional[float] = None  # mean result per trade after costs
    max_drawdown: Optional[float] = None
    period: Optional[str] = None
    direction_accuracy: Optional[float] = None  # separate from trade success and profitability
    direction_baseline: Optional[float] = None
    baseline_expectancy: Optional[float] = None  # same plan without the model
    qualified: Optional[bool] = None
    verdict: Optional[str] = None


class Check(BaseModel):
    """One entry condition (v1.7.3). ok=None means it cannot be checked right now (e.g. calendar not connected)."""
    model_config = ConfigDict(extra="forbid")
    code: str  # session | news | volatility | trend | level | reward_risk | model
    ok: Optional[bool] = None
    args: list[str] = Field(default_factory=list)
    # v1.12 (news): CONNECTED | NO_EVENTS | STALE | DISCONNECTED | NOT_CONFIGURED ; last successful calendar update
    state: Optional[str] = None
    updated_at: Optional[str] = None


class Scenario(BaseModel):
    """A level-based scenario to WATCH today (v1.7.2). Not a recommendation: no probability, no position size."""
    model_config = ConfigDict(extra="forbid")
    kind: str  # BULL | BEAR
    trigger: float
    trigger_level: str  # e.g. R1 / S1
    target: Optional[float] = None
    target_level: Optional[str] = None
    invalidation: Optional[float] = None
    # v1.13 descriptive history (not a forecast): share of similar past breaks that reached the same distance
    hist_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    hist_n: Optional[int] = None
    hist_days: Optional[int] = None


class ScenarioEvent(BaseModel):
    """v1.9: the last CLOSED hour broke a level (close crossed it). A fact to watch, not a recommendation."""
    model_config = ConfigDict(extra="forbid")
    kind: str  # BULL (closed above) | BEAR (closed below)
    level: float
    level_name: str
    target: Optional[float] = None
    target_name: Optional[str] = None
    hour_utc: datetime  # open time of the hour that closed across the level


class DailyBrief(BaseModel):
    """Every day, even when no trade is validated: today's bias and the two levels that would change the picture."""
    model_config = ConfigDict(extra="forbid")
    date: str
    bias: str  # UP | DOWN | SIDEWAYS | UNKNOWN (from the analytic trend, not a forecast probability)
    price: float
    scenarios: list[Scenario] = Field(default_factory=list)
    events: list[ScenarioEvent] = Field(default_factory=list)  # v1.9
    source: str = "H1_LEVELS"  # H1_LEVELS | DAILY_LEVELS


class HorizonOutlook(BaseModel):
    """Per-horizon view: HOURS mirrors the main intraday decision; WEEK / MONTH come from daily rules.

    hit_rate is the historical FREQUENCY of the validated rule (non-overlapping, after costs) — never a
    calibrated probability of this particular trade, and never reported for unvalidated rules or in DEMO.
    """
    model_config = ConfigDict(extra="forbid")
    horizon: str  # HOURS | WEEK | MONTH
    label_ar: str
    action: Action
    tilt: int = Field(default=0, ge=-1, le=1)
    stance_ar: str
    reason_ar: str
    validated: bool = False
    validation_ar: Optional[str] = None
    hit_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    base_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    samples: int = 0
    horizon_days: Optional[int] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    wait_for_price: Optional[float] = None
    method_ar: Optional[str] = None
    warnings_ar: list[str] = Field(default_factory=list)
    # translatable twins of the Arabic fields + the horizon's own full payload (v1.5)
    stance_ref: Optional[ReasonRef] = None
    reason_ref: Optional[ReasonRef] = None
    validation_ref: Optional[ReasonRef] = None
    method_ref: Optional[ReasonRef] = None
    warnings_ref: list[ReasonRef] = Field(default_factory=list)
    facts_ref: list[ReasonRef] = Field(default_factory=list)
    levels: Optional["LevelsBlock"] = None
    trend: Optional["MarketTrend"] = None
    probabilities_available: bool = False  # only HOURS can carry calibrated probabilities
    # live forward record (v1.6): outcomes of past signals of this horizon recorded BEFORE they resolved.
    # A frequency, never a probability; HOURS comes from the server's paper ledger (resets on redeploys).
    live_resolved: int = Field(default=0, ge=0)
    live_hits: int = Field(default=0, ge=0)
    checklist: list[Check] = Field(default_factory=list)  # v1.7.3 live entry conditions
    plan: Optional[TradePlan] = None  # v1.7
    performance: list[PerfStats] = Field(default_factory=list)

    @model_validator(mode="after")
    def _honest(self) -> "HorizonOutlook":
        if self.hit_rate is not None and (not self.validated or self.samples < 30):
            raise ValueError("a hit rate requires a validated rule with >= 30 samples")
        if self.action in (Action.BUY, Action.SELL) and self.horizon != "HOURS":
            if not self.validated:
                raise ValueError("WEEK/MONTH BUY/SELL requires a validated rule")
            if None in (self.entry_price, self.stop_loss, self.target):
                raise ValueError("WEEK/MONTH BUY/SELL requires entry, stop and target")
            sgn = 1 if self.action == Action.BUY else -1
            if not (sgn * (self.target - self.entry_price) > 0 > sgn * (self.stop_loss - self.entry_price)):
                raise ValueError("outlook levels inconsistent with direction")
        return self


class DQCheck(BaseModel):
    """One automatic data-quality check (v1.8). status: OK | WARN | FAIL."""
    model_config = ConfigDict(extra="forbid")
    code: str  # freshness | coverage | gaps | outliers | flat | weekend | ohlc | cross_source
    status: str
    value: Optional[str] = None
    tf: Optional[str] = None


class DataHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str  # OK | WARN | FAIL — FAIL blocks the decision
    checks: list[DQCheck] = Field(default_factory=list)


class ScalpActivity(BaseModel):
    """v1.10: will price move at least target_pct (either way) within `hours`? NOT a direction, never a BUY/SELL.
    Present only for assets whose forecast passed the weekly pre-registered validation (goldquant/activity.py)."""
    model_config = ConfigDict(extra="forbid")
    probability: float = Field(ge=0.0, le=1.0)
    usual: float = Field(ge=0.0, le=1.0)  # the normal rate for this hour of the week
    level: str  # HIGH | NORMAL | LOW (vs usual)
    target_pct: float
    hours: float
    skill: Optional[float] = None  # Brier skill vs usual, all out-of-sample years
    holdout_skill: Optional[float] = None
    validated_period: Optional[str] = None
    model_fitted_until: Optional[str] = None


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    decision_id: str
    mode: Mode
    action: Action
    instrument: str = "XAU/USD"
    spot_or_proxy: SpotOrProxy
    provider: str
    quote: Optional[float] = None
    quote_timestamp_utc: Optional[datetime] = None
    analyzed_at_utc: datetime

    entry_min: Optional[float] = None
    entry_max: Optional[float] = None
    stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    horizon_minutes: Optional[int] = None
    valid_until_utc: Optional[datetime] = None

    probability_target_before_stop: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    probability_stop_before_target: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    probability_neither: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    probabilities_by_horizon: list[HorizonProbability] = Field(default_factory=list)
    probability_reliability_ar: Optional[str] = None
    probability_method: str = "none"
    calibration_sample_count: int = 0
    calibration_period: Optional[str] = None
    model_version: str

    expected_net_return: Optional[float] = None
    estimated_cost: Optional[float] = None
    reward_risk: Optional[float] = None
    market_regime: Optional[str] = None
    vol_regime: Optional[str] = None  # STRONG_TREND | RANGE | HIGH_VOL | EXCEPTIONAL
    uncertainty: Optional[Uncertainty] = None
    reason_short_ar: Optional[str] = None
    alternative_entry_price: Optional[float] = None
    alternative_entry_note_ar: Optional[str] = None
    engines_used: list[str] = Field(default_factory=list)
    court: list[CourtJudgement] = Field(default_factory=list)
    market_trend: Optional[MarketTrend] = None
    levels: Optional[LevelsBlock] = None
    quote_change: Optional[float] = None
    quote_change_pct: Optional[float] = None
    reevaluate_ar: list[str] = Field(default_factory=list)
    reevaluate_refs: list[ReasonRef] = Field(default_factory=list)
    outlooks: list[HorizonOutlook] = Field(default_factory=list)
    # v1.7: the market is closed (weekend / daily break); trend and levels are those of the LAST session, for planning
    market_closed: bool = False
    daily_brief: Optional[DailyBrief] = None
    data_health: Optional[DataHealth] = None  # v1.8
    scalp_activity: Optional[ScalpActivity] = None  # v1.10
    audit_hash: Optional[str] = None

    supporting_evidence: list[Evidence] = Field(default_factory=list)
    contrary_evidence: list[Evidence] = Field(default_factory=list)
    invalidation_ar: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    data_freshness: DataFreshness
    data_quality: str  # GOOD | DEGRADED | INSUFFICIENT
    warning_ar: Optional[str] = None
    wait_for_ar: Optional[str] = None
    wait_for_price: Optional[float] = None
    snapshot_hash: str
    reason_short_ref: Optional[ReasonRef] = None
    alternative_entry_note_ref: Optional[ReasonRef] = None
    wait_for_ref: Optional[ReasonRef] = None
    warning_ref: Optional[ReasonRef] = None
    invalidation_refs: list[ReasonRef] = Field(default_factory=list)
    missing_refs: list[ReasonRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistency(self) -> "Decision":
        trade = self.action in (Action.BUY, Action.SELL)
        if trade:
            needed = [self.entry_min, self.entry_max, self.stop_loss, self.tp1, self.horizon_minutes,
                      self.valid_until_utc, self.quote, self.quote_timestamp_utc]
            if any(v is None for v in needed):
                raise ValueError("BUY/SELL requires entry, stop, tp1, horizon, validity and quote")
            if self.entry_min > self.entry_max:
                raise ValueError("entry_min > entry_max")
            if self.action == Action.BUY and not (self.stop_loss < self.entry_min and self.tp1 > self.entry_max):
                raise ValueError("BUY levels inconsistent")
            if self.action == Action.SELL and not (self.stop_loss > self.entry_max and self.tp1 < self.entry_min):
                raise ValueError("SELL levels inconsistent")
            if not self.data_freshness.is_fresh:
                raise ValueError("cannot emit a trade on stale data")
            if not self.court or not all(j.passed for j in self.court):
                raise ValueError("BUY/SELL requires every Decision Court judge to approve")
        probs = [self.probability_target_before_stop, self.probability_stop_before_target, self.probability_neither]
        if any(p is not None for p in probs) or self.probabilities_by_horizon:
            if self.mode == Mode.DEMO:
                raise ValueError("probabilities are never reported in DEMO mode")
            if self.calibration_sample_count < 300:
                raise ValueError("probability requires >=300 out-of-sample calibration samples")
        if all(p is not None for p in probs) and abs(sum(probs) - 1.0) > 1e-3:
            raise ValueError("outcome probabilities must sum to 1")
        if self.probability_target_before_stop is not None:
            if self.mode == Mode.DEMO:
                raise ValueError("probabilities are never reported in DEMO mode")
            if self.calibration_sample_count < 300:
                raise ValueError("probability requires >=300 out-of-sample calibration samples")
        if self.mode == Mode.DEMO and any(o.hit_rate is not None for o in self.outlooks):
            raise ValueError("historical hit rates are never reported in DEMO mode")
        if self.mode == Mode.DEMO and self.spot_or_proxy != SpotOrProxy.SYNTHETIC:
            raise ValueError("DEMO mode must be labelled SYNTHETIC")
        return self
