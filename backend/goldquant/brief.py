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


K_GRID = [round(0.25 * i, 2) for i in range(1, 33)]  # 0.25 .. 8.0 ATR (gold levels are often 4-8 ATR apart)


def history_table(h1) -> dict:
    """Pre-computed in CI over the last two years of hourly bars: {kind: {k: [rate, n]}} + the first-touch table."""
    out = {"days": 0, "BULL": {}, "BEAR": {}}
    for kind in ("BULL", "BEAR"):
        for k in K_GRID:
            r, n, days = history_rate(h1, kind, k)
            out[kind][str(k)] = [r, n]
            out["days"] = days
    out["first_touch"] = first_touch_table(h1)
    return out


# ---------------------------------------------------------------- which level is touched first (descriptive)
FT_WINDOW = 48  # hours
FT_GRID = [round(0.5 * i, 1) for i in range(1, 13)]  # 0.5 .. 6.0 ATR
FT_STRIDE = 6  # one case every 6 hours
FT_MIN_N, FT_MIN_N_HOLD, FT_MAX_GAP = 300, 80, 0.05


def first_touch_table(h1) -> dict:
    """With the price `a` ATR above a level and `b` ATR below another, how often was the LOWER one reached first
    within 48 h (cases where one of them was reached; same-hour touches are left out)? Pure price history: it does
    not know about support / resistance, so it mostly reflects the two distances. A cell is usable only with >= 300
    cases AND the same rate within 5 points on the last 20 % of the period (checked out of sample, never tuned)."""
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view as win
    if h1 is None or len(h1) < 2000:
        return {"window_hours": FT_WINDOW, "cells": {}}
    h, lo, c = (h1[x].to_numpy(float) for x in ("high", "low", "close"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - lo, np.maximum(np.abs(h - pc), np.abs(lo - pc)))
    atr = pd_rolling_mean(tr, 14)
    idx = np.arange(20, len(c) - FT_WINDOW - 1, FT_STRIDE)
    idx = idx[np.isfinite(atr[idx]) & (atr[idx] > 0)]
    H = win(h[1:], FT_WINDOW)[idx]  # bars t+1 .. t+48
    L = win(lo[1:], FT_WINDOW)[idx]
    up = (np.maximum.accumulate(H, axis=1) - c[idx, None]) / atr[idx, None]
    dn = (c[idx, None] - np.minimum.accumulate(L, axis=1)) / atr[idx, None]
    inf = FT_WINDOW + 1

    def first(m, g):
        hit = m >= g
        return np.where(hit.any(axis=1), hit.argmax(axis=1), inf)
    fu = {g: first(up, g) for g in FT_GRID}
    fd = {g: first(dn, g) for g in FT_GRID}
    split = int(len(idx) * 0.8)
    cells = {}
    for a in FT_GRID:  # a = distance DOWN to the lower level
        for b in FT_GRID:  # b = distance UP to the upper level
            d_, u_ = fd[a], fu[b]
            ok = (np.minimum(d_, u_) < inf) & (d_ != u_)
            down = d_ < u_
            n, n_h = int(ok.sum()), int(ok[split:].sum())
            if n == 0:
                continue
            p = float(down[ok].mean())
            p_tr = float(down[:split][ok[:split]].mean()) if ok[:split].any() else None
            p_h = float(down[split:][ok[split:]].mean()) if n_h else None
            usable = (n >= FT_MIN_N and n_h >= FT_MIN_N_HOLD and p_tr is not None and p_h is not None
                      and abs(p_tr - p_h) <= FT_MAX_GAP)
            cells[f"{a}|{b}"] = [round(p, 3), n, round(p_h, 3) if p_h is not None else None, n_h, usable]
    return {"window_hours": FT_WINDOW, "days": int((h1.index[-1] - h1.index[0]).days), "cells": cells}


# ---------------------------------------------------------------- three outcomes of the day (v1, PRE-REGISTERED)
OC_VERSION = "outcome3-0.1.0"
OC_WINDOW = {"crypto": 24, "gold": 23}  # one day: 24 hourly bars (gold: 23 trading hours), as the price ranges
OC_MIN_N, OC_MIN_N_HOLD, OC_MAX_GAP, OC_LEAD = 300, 80, 0.05, 0.05
OC_PREREG = """PRE-REGISTERED 2026-11-17, committed before any result was computed (owner's request: one clear 'most
likely' with percentages that never contradict the range or the trend).
Question: with the price `a` ATR(14, H1) above the lower scenario level and `b` ATR below the upper one, what happens
in the next day (24 hourly bars; gold 23 trading hours)? Three outcomes that add up to 100 %:
  DOWN = the lower level is reached first, UP = the upper level is reached first, NONE = neither is reached.
Cases where both are first reached in the same hour are left out (direction unknown). Same grid (0.5 .. 6.0 ATR in
steps of 0.5), same stride (one case every 6 hours), same history (last two years), same ATR as first_touch_table.
A cell is usable only with >= 300 cases, >= 80 of them in the last 20 % of the period, AND each of the three rates
within 5 points between the first 80 % and the last 20 % (out of sample). 'Most likely' is shown only when the top
outcome leads the second by >= 5 points; otherwise the app says there is no clear most-likely outcome today.
Nothing is tuned after seeing results; if few cells pass, few are shown."""


def outcome_table(h1, window: int) -> dict:
    """Three-outcome table (OC_PREREG). cells['a|b'] = [p_down, p_up, p_none, n, p_down_h, p_up_h, p_none_h, n_h, usable]."""
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view as win
    if h1 is None or len(h1) < 2000:
        return {"version": OC_VERSION, "window_hours": window, "cells": {}}
    h, lo, c = (h1[x].to_numpy(float) for x in ("high", "low", "close"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - lo, np.maximum(np.abs(h - pc), np.abs(lo - pc)))
    atr = pd_rolling_mean(tr, 14)
    idx = np.arange(20, len(c) - window - 1, FT_STRIDE)
    idx = idx[np.isfinite(atr[idx]) & (atr[idx] > 0)]
    H = win(h[1:], window)[idx]
    L = win(lo[1:], window)[idx]
    up = (np.maximum.accumulate(H, axis=1) - c[idx, None]) / atr[idx, None]
    dn = (c[idx, None] - np.minimum.accumulate(L, axis=1)) / atr[idx, None]
    inf = window + 1

    def first(m, g):
        hit = m >= g
        return np.where(hit.any(axis=1), hit.argmax(axis=1), inf)
    fu = {g: first(up, g) for g in FT_GRID}
    fd = {g: first(dn, g) for g in FT_GRID}
    split = int(len(idx) * 0.8)
    cells = {}
    for a in FT_GRID:
        for b in FT_GRID:
            d_, u_ = fd[a], fu[b]
            ok = ~((d_ == u_) & (d_ < inf))  # same-hour double touch: left out
            cls = np.where(d_ < u_, 0, np.where(u_ < d_, 1, 2))  # 0 DOWN, 1 UP, 2 NONE

            def rates(m):
                k = int(m.sum())
                return ([round(float((cls[m] == j).mean()), 3) for j in range(3)] if k else [None] * 3), k
            r, n = rates(ok)
            if n == 0:
                continue
            tr_m = ok.copy(); tr_m[split:] = False
            ho_m = ok.copy(); ho_m[:split] = False
            r_tr, _ = rates(tr_m)
            r_h, n_h = rates(ho_m)
            usable = (n >= OC_MIN_N and n_h >= OC_MIN_N_HOLD and None not in r_tr and None not in r_h
                      and all(abs(x - y) <= OC_MAX_GAP for x, y in zip(r_tr, r_h)))
            cells[f"{a}|{b}"] = r + [n] + r_h + [n_h, usable]
    return {"version": OC_VERSION, "window_hours": window, "days": int((h1.index[-1] - h1.index[0]).days),
            "cells": cells}


def pd_rolling_mean(x, n):
    import numpy as np
    import pandas as pd
    return pd.Series(x).rolling(n).mean().to_numpy(dtype=float) if len(x) else np.array([])


def attach_first_touch(brief, table: dict | None, price: float, s1: float | None, r1: float | None, atr_now) -> None:
    """Fill brief.first_touch for the two scenario levels, only from a usable cell (see first_touch_table)."""
    from .schemas import FirstTouch
    if brief is None or not table or not atr_now or s1 is None or r1 is None or not (s1 < price < r1):
        return
    ft = table.get("first_touch") or {}
    a, b = (price - s1) / float(atr_now), (r1 - price) / float(atr_now)
    ga, gb = min(FT_GRID, key=lambda g: abs(g - a)), min(FT_GRID, key=lambda g: abs(g - b))
    if abs(ga - a) > 0.25 or abs(gb - b) > 0.25:
        return
    cell = (ft.get("cells") or {}).get(f"{ga}|{gb}")
    if not cell or not cell[4]:
        return
    brief.first_touch = FirstTouch(down_first=cell[0], up_first=round(1 - cell[0], 3), n=cell[1],
                                   days=ft.get("days") or 0, window_hours=ft.get("window_hours") or FT_WINDOW,
                                   down_level=round(s1, 2), up_level=round(r1, 2))


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
