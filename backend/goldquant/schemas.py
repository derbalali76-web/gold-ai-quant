"""Typed signal contract shared with the Android app (schema/decision.schema.json is generated from this)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.3.0"


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


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: str
    text_ar: str
    weight: float = Field(ge=-1.0, le=1.0)


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
        if self.mode == Mode.DEMO and self.spot_or_proxy != SpotOrProxy.SYNTHETIC:
            raise ValueError("DEMO mode must be labelled SYNTHETIC")
        return self
