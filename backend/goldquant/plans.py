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


def planner_plan(d: Decision, o: HorizonOutlook, pm, daily) -> TradePlan | None:
    """Qualified planner (v1.7.1): its best plan becomes the horizon's recommendation (LIVE only).
    Returns None when the planner is absent / not qualified, so the rule-based plan is used instead."""
    if pm is None or not pm.qualified or daily is None or d.mode != Mode.LIVE or o.action == Action.UNAVAILABLE:
        return None
    closed = daily[daily.index + timedelta(days=1) <= d.analyzed_at_utc]
    bp = pm.best_plan(closed) if len(closed) else None
    if bp is None:
        return TradePlan(setup=Setup.WAIT, method="PLANNER")
    buy = bp["direction"] > 0
    cal = bool(pm.report.get("probabilities_calibrated"))
    market = bp["entry_kind"] == "MARKET"
    setup = (Setup.BUY_NOW if buy else Setup.SELL_NOW) if market else (Setup.WAIT_TO_BUY if buy else Setup.WAIT_TO_SELL)
    o.action, o.tilt, o.validated = (Action.BUY if buy else Action.SELL) if market else Action.WAIT, bp["direction"], True
    o.entry_price, o.stop_loss, o.target = bp["entry"], bp["stop"], bp["target"]
    return TradePlan(
        setup=setup, recommendation=True, side="BUY" if buy else "SELL", order="MARKET" if market else "LIMIT",
        entry_low=bp["entry"], entry_high=bp["entry"], watch_price=None if market else bp["entry"],
        stop_loss=bp["stop"], target=bp["target"], reward_risk=_rr(bp["entry"], bp["stop"], bp["target"]),
        expected_days=bp["horizon_days"], fill_days=bp["fill_days"] or None, method="PLANNER",
        valid_until_utc=d.analyzed_at_utc + timedelta(days=max(1, bp["fill_days"] or 1)),
        median_days_to_target=bp["median_days_to_target"] if cal else None,
        expected_net_return_pct=bp["ev_pct"] if cal else None,
        p_target_first=bp["p_target"] if cal else None, p_stop_first=bp["p_stop"] if cal else None,
        p_timeout=bp["p_timeout"] if cal else None, p_fill=(bp["p_fill"] if not market else None) if cal else None)


def attach(d: Decision, planners: dict | None = None, daily=None) -> Decision:
    for o in d.outlooks:
        if o.horizon == "HOURS":
            o.plan = hours_plan(d, o)
        else:
            o.plan = planner_plan(d, o, (planners or {}).get(o.horizon), daily) or daily_plan(d, o)
            if o.plan.method is None:
                o.plan.method = "RULE"
    return d
