"""Trade plans (v1.7): turn each horizon's analysis into the six user-facing setups.

Nothing here creates a trade. A plan only re-expresses what the engine already decided:
- BUY_NOW / SELL_NOW exist only where the engine itself said BUY / SELL; they are a *recommendation* only in LIVE
  mode for a validated horizon.
- WAIT_TO_BUY / WAIT_TO_SELL are WATCH levels (a lean plus a price to watch). They carry no stop or target, so a
  watch level can never be read as a trade.
"""
from __future__ import annotations

from datetime import timedelta

from .schemas import Action, Decision, HorizonOutlook, Mode, Setup, TradePlan


def _rr(entry: float, stop: float, target: float) -> float | None:
    risk = abs(entry - stop)
    return round(abs(target - entry) / risk, 2) if risk > 0 else None


def _wait_plan(tilt: int, watch: float | None) -> TradePlan:
    if tilt and watch is not None:
        return TradePlan(setup=Setup.WAIT_TO_BUY if tilt > 0 else Setup.WAIT_TO_SELL,
                         side="BUY" if tilt > 0 else "SELL", order="LIMIT", watch_price=round(float(watch), 2))
    return TradePlan(setup=Setup.WAIT)


def hours_plan(d: Decision, o: HorizonOutlook) -> TradePlan:
    if d.action == Action.UNAVAILABLE:
        return TradePlan(setup=Setup.UNAVAILABLE)
    if d.action in (Action.BUY, Action.SELL) and None not in (d.entry_min, d.entry_max, d.stop_loss, d.tp1):
        buy = d.action == Action.BUY
        mid = (d.entry_min + d.entry_max) / 2
        return TradePlan(setup=Setup.BUY_NOW if buy else Setup.SELL_NOW,
                         recommendation=d.mode == Mode.LIVE and o.validated,
                         side=d.action.value, order="MARKET", entry_low=d.entry_min, entry_high=d.entry_max,
                         stop_loss=d.stop_loss, target=d.tp1,
                         reward_risk=d.reward_risk if d.reward_risk is not None else _rr(mid, d.stop_loss, d.tp1),
                         expected_minutes=d.horizon_minutes, valid_until_utc=d.valid_until_utc,
                         invalidation_refs=list(d.invalidation_refs))
    return _wait_plan(o.tilt, d.wait_for_price if d.action == Action.WAIT else None)


def daily_plan(d: Decision, o: HorizonOutlook) -> TradePlan:
    if o.action == Action.UNAVAILABLE:
        return TradePlan(setup=Setup.UNAVAILABLE)
    if o.action in (Action.BUY, Action.SELL) and None not in (o.entry_price, o.stop_loss, o.target):
        buy = o.action == Action.BUY
        return TradePlan(setup=Setup.BUY_NOW if buy else Setup.SELL_NOW,
                         recommendation=d.mode == Mode.LIVE and o.validated,
                         side=o.action.value, order="MARKET", entry_low=o.entry_price, entry_high=o.entry_price,
                         stop_loss=o.stop_loss, target=o.target, reward_risk=_rr(o.entry_price, o.stop_loss, o.target),
                         expected_days=o.horizon_days,
                         valid_until_utc=d.analyzed_at_utc + timedelta(days=1))  # re-checked on the next daily bar
    return _wait_plan(o.tilt, o.wait_for_price)


def attach(d: Decision) -> Decision:
    for o in d.outlooks:
        o.plan = hours_plan(d, o) if o.horizon == "HOURS" else daily_plan(d, o)
    return d
