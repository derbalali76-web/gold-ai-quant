"""AI QUANT Trade Engine — features and the pre-registered rule family (te-0.1.0).

Every feature at decision time t uses only 4h bars that CLOSED at or before t (the bar's open time + 4h <= t).
Decision time = open time of the signalling bar + 4h. No fitted parameters: the rules are fixed formulas.
"""
from __future__ import annotations
import itertools
import numpy as np
import pandas as pd

from .sim import Order, H4

DEV_START = pd.Timestamp("2021-01-01", tz="UTC")       # first month with 15m bars for both assets
HOLDOUT_START = pd.Timestamp("2025-11-15", tz="UTC")   # last 12 months of stored data: sealed until phase 3
HOLDOUT_END = pd.Timestamp("2026-11-15", tz="UTC")
FOLDS = [("2022-01-01", "2023-01-01"), ("2023-01-01", "2024-01-01"), ("2024-01-01", "2025-01-01"),
         ("2025-01-01", "2025-11-15")]                 # walk-forward test windows inside development data
EMBARGO = pd.Timedelta(days=7)                          # > entry timeout + max hold (36 bars = 6 days)
ENTRY_BARS, HOLD_BARS = 3, 30


def features(h4: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = h4["close"], h4["high"], h4["low"], h4["volume"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    f = pd.DataFrame({
        "close": c, "low": l,
        "atr": tr.ewm(alpha=1 / 14, adjust=False).mean(),
        "rsi": 100 - 100 / (1 + up / dn.replace(0, np.nan)),
        "ema50": c.ewm(span=50, adjust=False).mean(), "ema200": c.ewm(span=200, adjust=False).mean(),
        "sma20": c.rolling(20).mean(), "sd20": c.rolling(20).std(),
        "hh20": h.shift(1).rolling(20).max(),          # highest high of the 20 bars BEFORE this one
        "vol_ratio": v / v.shift(1).rolling(20).mean(),
    }, index=h4.index)
    f["t"] = f.index + H4                              # decision time = bar close
    return f.iloc[250:]                                # warm-up for EMA200


# ---- the 24 pre-registered configurations (8 per family) -----------------------------------------------------
def configs() -> list[dict]:
    out = []
    for k, m, r in itertools.product((0.25, 0.75), (1.5, 2.5), (1.0, 2.0)):
        out.append({"id": f"A_pull_k{k}_m{m}_r{r}", "family": "A", "k": k, "m": m, "r": r, "timeout": ENTRY_BARS})
    for to, m, r in itertools.product((3, 6), (1.5, 2.5), (1.0, 2.0)):
        out.append({"id": f"B_break_to{to}_m{m}_r{r}", "family": "B", "m": m, "r": r, "timeout": to})
    for k, m, tgt in itertools.product((0.0, 0.5), (1.5, 2.5), ("sma20", "r1.5")):
        out.append({"id": f"C_bounce_k{k}_m{m}_{tgt}", "family": "C", "k": k, "m": m, "tgt": tgt, "timeout": ENTRY_BARS})
    return out


def signal(f: pd.DataFrame, cfg: dict) -> pd.Series:
    if cfg["family"] == "A":   # pullback inside an uptrend
        return (f["close"] > f["ema200"]) & (f["ema50"] > f["ema200"]) & (f["rsi"] < 40)
    if cfg["family"] == "B":   # close above the prior 20-bar high on above-average volume; buy the retest
        return (f["close"] > f["hh20"]) & (f["vol_ratio"] > 1.5)
    if cfg["family"] == "C":   # oversold below the lower Bollinger band
        return (f["close"] < f["sma20"] - 2 * f["sd20"]) & (f["rsi"] < 30)
    raise ValueError(cfg["family"])


def order_at(row: pd.Series, cfg: dict) -> Order | None:
    a = row["atr"]
    if cfg["family"] == "A":
        lim = row["close"] - cfg["k"] * a
    elif cfg["family"] == "B":
        lim = row["hh20"]
    else:
        lim = row["close"] - cfg["k"] * a
    stop = lim - cfg["m"] * a
    if cfg.get("tgt") == "sma20":
        target = row["sma20"]
        if target <= lim * 1.003:          # structure target too close to cover costs: no order
            return None
    else:
        r = cfg.get("r", 1.5) if cfg.get("tgt") != "r1.5" else 1.5
        target = lim + r * (lim - stop)
    if not (stop > 0 and stop < lim < target):
        return None
    return Order(row["t"], target=float(target), stop=float(stop), limit=float(lim),
                 entry_bars=cfg["timeout"], hold_bars=HOLD_BARS)


def orders(f: pd.DataFrame, cfg: dict, start: pd.Timestamp, end: pd.Timestamp) -> list[Order]:
    """Orders whose decision time lies in [start, end). Refuses to touch the sealed holdout."""
    if end > HOLDOUT_START and not _holdout_unsealed():
        raise PermissionError("holdout is sealed until phase 3 (pre-registration te-0.1.0)")
    sel = f[(f["t"] >= start) & (f["t"] < end)]
    sig = signal(sel, cfg)
    return [o for _, row in sel[sig].iterrows() if (o := order_at(row, cfg)) is not None]


def _holdout_unsealed() -> bool:
    import os
    return os.environ.get("TE_UNSEAL_HOLDOUT") == "te-0.1.0"
