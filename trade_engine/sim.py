"""AI QUANT Trade Engine — spot, long-only trade simulator (experimental, research only).

One trade = an order decided at the CLOSE of a 4h bar (decision time t). Nothing after t is read to decide.

Order life cycle (all prices in quote currency, returns as fractions of the entry price):
  1. Entry. LIMIT buy at `limit` (resting, maker fee) or MARKET buy at the next bar's open (taker fee, plus
     half-spread and slippage). A resting limit fills only when price trades STRICTLY BELOW it (low < limit):
     a mere touch is not a fill (queue position unknown). If a bar opens below the limit, the fill is that open.
     Not filled within `entry_bars` 4h bars -> NOT_FILLED (cancelled, zero return, no fee).
  2. Exits once filled: take-profit LIMIT sell at `target` (maker; fills only when high > target strictly, or at the
     open if the bar opens above it); stop-loss STOP-MARKET at `stop` (taker; triggers when low <= stop, fills at
     min(stop, open) minus slippage); time exit at the close of the `hold_bars`-th 4h bar after the fill (taker,
     minus half-spread and slippage).
  3. Order of events inside a bar is resolved on 15m bars where available, else 1h. Within one resolution bar:
     - stop and target both reachable -> STOP (conservative);
     - the bar in which the entry fills: the stop may trigger in it (price went down there), the target may not
       (we cannot know it came after the fill).
Costs are charged on both sides. Fees, spread and slippage are parameters, recorded with every result.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional
import numpy as np
import pandas as pd

H4 = pd.Timedelta(hours=4)


@dataclass(frozen=True)
class Costs:
    maker: float = 0.0010      # Binance spot regular tier, maker and taker 0.10 % (checked 2026-11-18)
    taker: float = 0.0010
    half_spread: float = 0.0001  # paid on market orders only (limits rest at their price)
    slippage: float = 0.0005     # extra adverse move on market and stop orders

    @staticmethod
    def for_asset(asset: str, stress: float = 1.0) -> "Costs":
        base = {"BTCUSDT": Costs(0.0010, 0.0010, 0.0001, 0.0005), "SOLUSDT": Costs(0.0010, 0.0010, 0.0002, 0.0010)}[asset]
        return Costs(base.maker * stress, base.taker * stress, base.half_spread * stress, base.slippage * stress)


@dataclass(frozen=True)
class Order:
    t: pd.Timestamp            # decision time = close of the signalling 4h bar (UTC)
    target: float
    stop: float
    limit: Optional[float] = None   # None -> market entry at the next bar's open
    entry_bars: int = 3             # entry timeout, in 4h bars
    hold_bars: int = 30             # max holding time after the fill, in 4h bars


@dataclass
class Result:
    t: str
    filled: bool
    outcome: str                 # NOT_FILLED | TARGET | STOP | TIME | NO_DATA
    entry: Optional[float] = None
    exit: Optional[float] = None
    fill_time: Optional[str] = None
    exit_time: Optional[str] = None
    gross: float = 0.0           # exit / entry - 1 after spread and slippage, before fees
    net: float = 0.0             # after fees, spread and slippage on both sides
    bars_held: int = 0           # 4h bars from fill to exit (rounded up)
    mae: float = 0.0             # worst low vs entry while held
    mfe: float = 0.0             # best high vs entry while held

    def row(self) -> dict:
        return asdict(self)


class Market:
    """Fine bars used to walk orders forward. `fine` must be 15m or 1h OHLC indexed by open time (UTC)."""

    def __init__(self, fine_15m: Optional[pd.DataFrame], fine_1h: pd.DataFrame):
        parts = []
        if fine_15m is not None and len(fine_15m):
            start15, end15 = fine_15m.index[0], fine_15m.index[-1] + pd.Timedelta(minutes=15)
            outside = (fine_1h.index < start15) | (fine_1h.index >= end15)  # 1h only where 15m does not cover
            parts.append(fine_1h[outside].assign(step=pd.Timedelta(hours=1)))
            parts.append(fine_15m.assign(step=pd.Timedelta(minutes=15)))
        else:
            parts.append(fine_1h.assign(step=pd.Timedelta(hours=1)))
        df = pd.concat(parts).sort_index()
        df = df[~df.index.duplicated(keep="last")]
        self.ix = df.index.values
        self.o, self.h, self.l, self.c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.step = df["step"].to_numpy()
        self.end = df.index[-1] + df["step"].iloc[-1]

    def window(self, start: pd.Timestamp, stop: pd.Timestamp) -> tuple[int, int]:
        a = int(np.searchsorted(self.ix, np.datetime64(start.tz_convert(None) if start.tzinfo else start)))
        b = int(np.searchsorted(self.ix, np.datetime64(stop.tz_convert(None) if stop.tzinfo else stop)))
        return a, b


def _ts(m: Market, i: int) -> str:
    return str(pd.Timestamp(m.ix[i]).tz_localize("UTC"))


def simulate(order: Order, m: Market, costs: Costs) -> Result:
    t = order.t
    entry_end = t + order.entry_bars * H4
    if entry_end + order.hold_bars * H4 > m.end:
        return Result(str(t), False, "NO_DATA")
    a, b = m.window(t, entry_end)
    if a >= b:
        return Result(str(t), False, "NO_DATA")
    # ---- entry
    if order.limit is None:
        fill_i = a
        entry = m.o[a] * (1 + costs.half_spread + costs.slippage)
        buy_fee = costs.taker
    else:
        fill_i, entry = None, None
        for i in range(a, b):
            if m.o[i] < order.limit:
                fill_i, entry = i, m.o[i]
                break
            if m.l[i] < order.limit:
                fill_i, entry = i, order.limit
                break
        if fill_i is None:
            return Result(str(t), False, "NOT_FILLED")
        buy_fee = costs.maker
    fill_t = pd.Timestamp(m.ix[fill_i]).tz_localize("UTC")
    hold_end = fill_t.floor("4h") + (order.hold_bars + 1) * H4  # the fill's 4h bar + hold_bars full 4h bars
    _, z = m.window(fill_t, hold_end)
    lo = hi = entry
    out, px, j = "TIME", None, None
    if entry <= order.stop:        # filled at or below the stop (gap): the stop is already triggered
        out, px, j = "STOP", entry * (1 - costs.slippage), fill_i
    elif entry >= order.target:    # filled at or above the target (market gap up): the resting sell fills at once
        out, px, j = "TARGET", entry, fill_i
    else:
        for i in range(fill_i, z):
            o, h, l = m.o[i], m.h[i], m.l[i]
            first = i == fill_i
            if not first and o <= order.stop:          # gap through the stop: filled at the open
                out, px, j = "STOP", o * (1 - costs.slippage), i
                break
            if not first and o > order.target:         # gap through the target: the resting sell fills at the open
                out, px, j = "TARGET", o, i
                break
            if l <= order.stop:                        # stop first when both are reachable in one bar
                lo = min(lo, l)
                out, px, j = "STOP", order.stop * (1 - costs.slippage), i
                break
            if not first and h > order.target:         # strictly through, like the entry
                hi = max(hi, h)
                out, px, j = "TARGET", order.target, i
                break
            lo, hi = min(lo, l), max(hi, h)
    if j is None:
        j = z - 1
        px = m.c[j] * (1 - costs.half_spread - costs.slippage)
    sell_fee = costs.maker if out == "TARGET" else costs.taker
    gross = px / entry - 1                                       # after spread/slippage, before fees
    net = (px * (1 - sell_fee)) / (entry * (1 + buy_fee)) - 1    # after everything
    exit_t = pd.Timestamp(m.ix[j]).tz_localize("UTC") + pd.Timedelta(m.step[j])
    bars = int(np.ceil((exit_t - fill_t) / H4))
    return Result(str(t), True, out, round(entry, 8), round(px, 8), _ts(m, fill_i), str(exit_t), round(gross, 6),
                  round(net, 6), bars, round(lo / entry - 1, 6), round(hi / entry - 1, 6))


def run(orders: list[Order], m: Market, costs: Costs, one_at_a_time: bool = True) -> list[Result]:
    """Orders in time order. With one_at_a_time, an order is skipped while an earlier one is pending or open."""
    out, busy_until = [], None
    for od in sorted(orders, key=lambda x: x.t):
        if one_at_a_time and busy_until is not None and od.t < busy_until:
            continue
        r = simulate(od, m, costs)
        out.append(r)
        if r.outcome == "NOT_FILLED":
            busy_until = od.t + od.entry_bars * H4
        elif r.filled:
            busy_until = pd.Timestamp(r.exit_time)
    return out
