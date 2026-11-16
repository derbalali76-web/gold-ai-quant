"""Data Quality Firewall (V4 #5): every input is checked before any analysis may use it.

Blocking failures => the decision is UNAVAILABLE (never a trade). Warnings are recorded in the audit trail.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from ..msg import M

MAX_CLOCK_SKEW = timedelta(seconds=5)
MAX_JUMP_ATR = 8.0  # quote vs last closed M15 close
FROZEN_RUN = 8  # identical consecutive bars => frozen feed
MAX_BAR_LAG = {"M15": timedelta(minutes=45), "H1": timedelta(hours=3), "H4": timedelta(hours=10)}
SPIKE_Z = 12.0


@dataclass
class FirewallResult:
    blocking: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.blocking


def _frozen(df: pd.DataFrame, run: int = FROZEN_RUN) -> bool:
    tail = df[["open", "high", "low", "close"]].tail(run)
    return len(tail) == run and (tail.nunique() == 1).all()


def check_market(quote, bars: dict, as_of: datetime, atr15: float | None, market_open: bool) -> FirewallResult:
    r = FirewallResult()
    if quote is not None:
        if quote.observed_at > as_of + MAX_CLOCK_SKEW:
            r.blocking.append(M("fw.future_ts"))
        if not np.isfinite(quote.price) or quote.price <= 0:
            r.blocking.append(M("fw.bad_price"))
        for w in getattr(quote, "warnings", []):
            (r.blocking if "تعارض" in w else r.warnings).append(w)
    m15 = bars.get("M15")
    if m15 is not None and len(m15):
        last_close = float(m15["close"].iloc[-1])
        if quote is not None and atr15 and atr15 > 0:
            jump = abs(quote.price - last_close) / atr15
            r.checks["quote_jump_atr"] = round(jump, 2)
            if jump > MAX_JUMP_ATR:
                r.blocking.append(M("fw.jump", f"{jump:.1f}"))
        if _frozen(m15):
            r.blocking.append(M("fw.frozen"))
        rets = np.log(m15["close"]).diff().tail(220).dropna()
        if len(rets) > 50:
            med = rets.median()
            mad = (rets - med).abs().median() * 1.4826
            if mad > 0:
                z = float(((rets.tail(20) - med).abs() / mad).max())
                r.checks["max_recent_return_z"] = round(z, 1)
                if z > SPIKE_Z:
                    r.blocking.append(M("fw.spike", f"{z:.0f}"))
    if market_open:
        for tf, lag in MAX_BAR_LAG.items():
            df = bars.get(tf)
            if df is None or df.empty:
                continue
            close_t = df.index[-1] + pd.Timedelta(minutes={"M15": 15, "H1": 60, "H4": 240}[tf])
            behind = open_time_between(close_t, pd.Timestamp(as_of))  # the weekly close is not a delay
            r.checks[f"{tf}_lag_min"] = round(behind.total_seconds() / 60, 1)
            if behind > lag:
                r.blocking.append(M("fw.bar_lag", tf, f"{behind.total_seconds() / 3600:.1f}"))
    return r


def open_time_between(start: pd.Timestamp, end: pd.Timestamp) -> pd.Timedelta:
    """Market-open time between two instants (weekly close Fri 17:00 -> Sun 18:00 New York excluded).
    Monday 05:40 UTC after a Friday 22:00 close is about 6.7 h behind, not 2 days."""
    from ..providers.base import market_closed_mask
    if end <= start:
        return pd.Timedelta(0)
    if end - start > pd.Timedelta(days=21):  # far behind anyway; no need to count
        return end - start
    grid = pd.date_range(start, end, freq="5min", inclusive="left")
    return pd.Timedelta(minutes=5 * int((~market_closed_mask(grid)).sum()))


def check_news(items: list, as_of: datetime) -> tuple[list, list]:
    """Quarantines news whose publication time is in the future (bad timestamps) — returns (kept, warnings)."""
    kept, warns = [], []
    for it in items:
        if it.published_at > as_of + timedelta(minutes=1):
            warns.append(M("md.news_future", it.source))
        else:
            kept.append(it)
    return kept, warns


def check_sources(mode_live: bool, context) -> FirewallResult:
    """LIVE signals need the critical non-price sources; their absence blocks trades (not the analysis)."""
    r = FirewallResult()
    if not mode_live:
        return r
    if context is None:
        r.blocking.append(M("fw.no_context"))
        return r
    if not context.calendar_connected:
        r.blocking.append(M("fw.calendar_stale"))
    if any("RSS" in m for m in context.missing):
        r.warnings.append(M("md.news_feeds"))
    return r
