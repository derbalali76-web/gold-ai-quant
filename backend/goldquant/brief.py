"""Daily brief (v1.7.2): today's bias plus the two watch scenarios (breakout up / breakdown), built only from
levels and trend the engine already computed. It is context for the user every day, never a recommendation."""
from __future__ import annotations

from .schemas import Decision, DailyBrief, Scenario, ScenarioEvent


def _levels(d: Decision):
    if d.levels and (d.levels.supports or d.levels.resistances):
        return d.levels.supports, d.levels.resistances, "H1_LEVELS"
    for o in d.outlooks:  # fall back on the daily levels of the WEEK outlook
        if o.horizon == "WEEK" and o.levels and (o.levels.supports or o.levels.resistances):
            return o.levels.supports, o.levels.resistances, "DAILY_LEVELS"
    return [], [], None


def build(d: Decision) -> DailyBrief | None:
    if d.quote is None:
        return None
    sup, res, src = _levels(d)
    if src is None:
        return None
    price = float(d.quote)
    sup = sorted([l for l in sup if l.price < price], key=lambda l: -l.price)
    res = sorted([l for l in res if l.price > price], key=lambda l: l.price)
    sc = []
    if res:
        r1 = res[0]
        sc.append(Scenario(kind="BULL", trigger=r1.price, trigger_level=r1.name,
                           target=res[1].price if len(res) > 1 else None, target_level=res[1].name if len(res) > 1 else None,
                           invalidation=sup[0].price if sup else None))
    if sup:
        s1 = sup[0]
        sc.append(Scenario(kind="BEAR", trigger=s1.price, trigger_level=s1.name,
                           target=sup[1].price if len(sup) > 1 else None, target_level=sup[1].name if len(sup) > 1 else None,
                           invalidation=res[0].price if res else None))
    bias = d.market_trend.direction if d.market_trend else "UNKNOWN"
    if bias == "DOWN":
        sc.reverse()
    if not sc:
        return None
    return DailyBrief(date=d.analyzed_at_utc.date().isoformat(), bias=bias, price=round(price, 2), scenarios=sc, source=src)


def events(d: Decision, h1) -> list[ScenarioEvent]:
    """Levels broken by the last CLOSED hour: previous close on one side, last close on the other. Uses every
    known level (not only the two nearest ones, which move with the price)."""
    if h1 is None or len(h1) < 2 or d.levels is None:
        return []
    c_prev, c_last = float(h1["close"].iloc[-2]), float(h1["close"].iloc[-1])
    lv = sorted(list(d.levels.supports) + list(d.levels.resistances), key=lambda l: l.price)
    out = []
    for i, l in enumerate(lv):
        if c_prev <= l.price < c_last:  # closed above
            nxt = lv[i + 1] if i + 1 < len(lv) else None
            out.append(ScenarioEvent(kind="BULL", level=l.price, level_name=l.name, target=nxt.price if nxt else None,
                                     target_name=nxt.name if nxt else None, hour_utc=h1.index[-1].to_pydatetime()))
        elif c_prev >= l.price > c_last:  # closed below
            nxt = lv[i - 1] if i > 0 else None
            out.append(ScenarioEvent(kind="BEAR", level=l.price, level_name=l.name, target=nxt.price if nxt else None,
                                     target_name=nxt.name if nxt else None, hour_utc=h1.index[-1].to_pydatetime()))
    return out
