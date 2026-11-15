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


HIST_MIN_N = 30
HIST_WINDOW = 24  # hours


def history_rate(h1, kind: str, k_atr: float) -> tuple:
    """How often did a SIMILAR break play out, on the bars we have? (fixed definition, descriptive only)
    similar break: an hourly close beyond the extreme of the previous 24 closed hours (below the lowest low for BEAR,
    above the highest high for BULL). Played out: within the next 24 hours the price went a further k x ATR(14) —
    the current trigger-to-target distance in ATR — BEFORE an hourly close back across the broken extreme.
    Returns (rate, n, days) or (None, n, days) when fewer than 30 cases exist."""
    import numpy as np
    import pandas as pd
    if h1 is None or len(h1) < 200 or not (k_atr > 0):
        return None, 0, 0
    h, lo, c = (h1[x].to_numpy(float) for x in ("high", "low", "close"))
    tr = np.maximum(h - lo, np.maximum(np.abs(h - np.r_[c[0], c[:-1]]), np.abs(lo - np.r_[c[0], c[:-1]])))
    atr = pd.Series(tr).rolling(14).mean().to_numpy()
    lowest = pd.Series(lo).rolling(HIST_WINDOW).min().shift(1).to_numpy()
    highest = pd.Series(h).rolling(HIST_WINDOW).max().shift(1).to_numpy()
    n = len(c)
    hits = tot = 0
    t = HIST_WINDOW + 15
    while t < n - HIST_WINDOW:
        if not np.isfinite(atr[t]):
            t += 1
            continue
        if kind == "BEAR" and c[t] < lowest[t] <= c[t - 1]:
            lvl, goal = lowest[t], c[t] - k_atr * atr[t]
            ok = False
            for j in range(t + 1, t + 1 + HIST_WINDOW):
                if lo[j] <= goal:
                    ok = True
                    break
                if c[j] > lvl:
                    break
        elif kind == "BULL" and c[t] > highest[t] >= c[t - 1]:
            lvl, goal = highest[t], c[t] + k_atr * atr[t]
            ok = False
            for j in range(t + 1, t + 1 + HIST_WINDOW):
                if h[j] >= goal:
                    ok = True
                    break
                if c[j] < lvl:
                    break
        else:
            t += 1
            continue
        tot += 1
        hits += ok
        t += HIST_WINDOW  # non-overlapping cases
    days = int((h1.index[-1] - h1.index[0]).days)
    return (round(hits / tot, 3) if tot >= HIST_MIN_N else None), tot, days


K_GRID = [round(0.25 * i, 2) for i in range(1, 17)]  # 0.25 .. 4.0 ATR


def history_table(h1) -> dict:
    """Pre-computed in CI over the last two years of hourly bars: {kind: {k: [rate, n]}}."""
    out = {"days": 0, "BULL": {}, "BEAR": {}}
    for kind in ("BULL", "BEAR"):
        for k in K_GRID:
            r, n, days = history_rate(h1, kind, k)
            out[kind][str(k)] = [r, n]
            out["days"] = days
    return out


def attach_history(brief, table: dict | None, atr_now) -> None:
    """Fill each scenario with the rate for the nearest pre-computed distance (rounded to 0.25 ATR)."""
    if brief is None or not table or not atr_now:
        return
    for sc in brief.scenarios:
        if sc.target is None:
            continue
        k = abs(sc.target - sc.trigger) / float(atr_now)
        kk = min(K_GRID, key=lambda g: abs(g - k))
        if abs(kk - k) > 0.25:  # outside the table: say nothing
            continue
        r, n = (table.get(sc.kind) or {}).get(str(kk), [None, 0])
        if r is not None:
            sc.hist_rate, sc.hist_n, sc.hist_days = r, n, table.get("days")
