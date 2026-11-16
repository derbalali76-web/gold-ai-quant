"""Per-source freshness for one decision (v1.14): when each input was last updated, and whether that is recent
enough. Shown to the user so an old analysis is never presented as live. Gold ages are counted in TRADING time (the
weekly close is not a delay); crypto trades 24/7. Limits mirror the gates that already block a decision
(reliability/firewall.py MAX_BAR_LAG); D1 and the activity model have their own limits here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from .schemas import SourceStatus

STEP_MIN = {"M15": 15, "H1": 60, "H4": 240, "D1": 1440}
MAX_AGE_MIN = {"PRICE": 15, "M15": 45, "H1": 180, "H4": 600, "D1": 2 * 1440 + 60, "ACTIVITY_MODEL": 9 * 1440}
DAILY_STALE = pd.Timedelta(minutes=MAX_AGE_MIN["D1"])


def age(last: pd.Timestamp, as_of: pd.Timestamp, gold_hours: bool) -> pd.Timedelta:
    from .reliability.firewall import open_time_between
    return open_time_between(last, as_of) if gold_hours else max(as_of - last, pd.Timedelta(0))


def _ts(x) -> Optional[pd.Timestamp]:
    if x is None:
        return None
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _one(source: str, last, as_of: pd.Timestamp, gold_hours: bool, market_closed: bool) -> SourceStatus:
    t = _ts(last)
    lim = MAX_AGE_MIN.get(source)
    if t is None:
        state = "DOWN"
    elif lim is not None and age(t, as_of, gold_hours) > pd.Timedelta(minutes=lim):
        state = "STALE"
    elif market_closed and source in ("PRICE", "M15", "H1", "H4", "D1"):
        state = "CLOSED"
    else:
        state = "OK"
    return SourceStatus(source=source, state=state, last_update_utc=None if t is None else t.to_pydatetime(),
                        max_age_minutes=lim)


def build(as_of: datetime, quote_time=None, bars: Optional[dict] = None, daily: Optional[pd.DataFrame] = None,
          ctx=None, gold_hours: bool = True, market_closed: bool = False,
          model_updated_at=None) -> list[SourceStatus]:
    a = _ts(as_of)
    out = [_one("PRICE", quote_time, a, gold_hours, market_closed)]
    for tf in ("M15", "H1", "H4"):
        df = (bars or {}).get(tf)
        if df is not None:
            last = df.index[-1] + pd.Timedelta(minutes=STEP_MIN[tf]) if len(df) else None
            out.append(_one(tf, last, a, gold_hours, market_closed))
    if daily is not None:
        d = daily[daily.index + pd.Timedelta(days=1) <= a] if len(daily) else daily
        out.append(_one("D1", d.index[-1] + pd.Timedelta(days=1) if len(d) else None, a, gold_hours, market_closed))
    if ctx is not None:
        st = getattr(ctx, "calendar_state", None)
        state = {"CONNECTED": "OK", "NO_EVENTS": "OK", "STALE": "STALE"}.get(st, "DOWN")
        out.append(SourceStatus(source="CALENDAR", state=state,
                                last_update_utc=None if not getattr(ctx, "calendar_updated_at", None)
                                else _ts(ctx.calendar_updated_at).to_pydatetime()))
    if model_updated_at is not None:
        out.append(_one("ACTIVITY_MODEL", model_updated_at, a, False, False))
    return out
