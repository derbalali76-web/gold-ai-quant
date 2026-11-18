"""AI QUANT Trade Engine te-0.2.0 — DRAFT hypotheses (not frozen until approved; see PREREG_v2.md).

Point-in-time rules (decision time t = close of a 4h bar):
  - spot 1h bars (price, volume, taker-buy volume): only bars whose CLOSE <= t;
  - funding (USD-M perpetual): only settlements with calc_time < t (strictly; the rate settled exactly at t is used
    from the next decision); a value older than 9 h is treated as missing (no signal);
  - futures metrics (open interest, hourly, last 5-min snapshot of the hour): only rows whose hour closed at least
    1 h before t (open_time + 2 h <= t);
  - every threshold is a percentile over a TRAILING window ending at t; nothing is normalised on the full sample.
"""
from __future__ import annotations
import glob
import itertools
from pathlib import Path
import numpy as np
import pandas as pd

from . import data
from .sim import Order, H4

ROOT = Path(__file__).resolve().parents[1] / "market_data" / "crypto"
ENTRY_K, ENTRY_BARS = 0.25, 3
EXITS = {"E5d": {"m": 2.0, "tp_atr": 3.0, "hold": 30}, "E24h": {"m": 1.5, "tp_atr": 1.5, "hold": 6}}


def _read(sym: str, kind: str) -> pd.DataFrame:
    parts = [pd.read_csv(f, compression="gzip") for f in sorted(glob.glob(str(ROOT / sym / kind / "*.csv.gz")))]
    df = pd.concat(parts)
    c = df.columns[0]
    df[c] = pd.to_datetime(df[c], utc=True, format="ISO8601")
    df = df.set_index(c).sort_index()
    return df[~df.index.duplicated(keep="last")]


def _trail_pct(s: pd.Series, days: int) -> pd.Series:
    """Percentile rank of each value within the trailing `days` window that ends at that value (inclusive)."""
    return s.rolling(f"{days}D", min_periods=30).apply(lambda a: (a <= a[-1]).mean(), raw=True)


def te_funding(sym: str) -> pd.Series:
    """Funding from the trade engine's own store (all months, Decembers included; see collect.py)."""
    parts = [pd.read_csv(f) for f in sorted(glob.glob(str(Path(__file__).resolve().parent / "data" / sym / "funding" / "*.csv")))]
    df = pd.concat(parts)
    s = pd.Series(df["funding"].astype(float).values, index=pd.to_datetime(df["calc_time_ms"], unit="ms", utc=True))
    return s[~s.index.duplicated(keep="last")].sort_index()


def clean_oi(sym: str) -> pd.Series:
    """Open interest per hour. The archive encodes missing snapshots as 0: those, and hours that appear twice
    (two files disagree about the hour's last snapshot), are treated as missing — never as real values."""
    raw = pd.concat([pd.read_csv(f, compression="gzip") for f in sorted(glob.glob(str(ROOT / sym / "metrics" / "*.csv.gz")))])
    raw["open_time"] = pd.to_datetime(raw["open_time"], utc=True, format="ISO8601")
    dup = raw["open_time"].duplicated(keep=False)
    s = raw[~dup].set_index("open_time").sort_index()["oi"].astype(float)
    return s[s > 0]


def features(sym: str, h1: pd.DataFrame, until: pd.Timestamp) -> pd.DataFrame:
    """4h decision rows with every input known at t. `h1` must already exclude bars at/after `until`."""
    raw = pd.concat([pd.read_csv(f, compression="gzip") for f in sorted(glob.glob(str(ROOT / sym / "1h" / "*.csv.gz")))])
    raw["open_time"] = pd.to_datetime(raw["open_time"], utc=True, format="ISO8601")
    tb = raw.drop_duplicates("open_time").set_index("open_time").sort_index()["taker_buy_volume"].astype(float)
    tb = tb[tb.index < until]
    h = h1.assign(tb=tb.reindex(h1.index))
    g = h.groupby(h.index.floor("4h"))
    b = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
              volume=("volume", "sum"), tb=("tb", "sum"), n=("close", "size"))
    b = b[b["n"] == 4].drop(columns="n")
    c, hi, lo = b["close"], b["high"], b["low"]
    tr = pd.concat([hi - lo, (hi - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    f = pd.DataFrame(index=b.index)
    f["t"] = b.index + H4
    f["close"] = c
    f["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    f["ret8"], f["ret12"], f["ret24"] = c / c.shift(2) - 1, c / c.shift(3) - 1, c / c.shift(6) - 1
    f["ret90d"] = c / c.shift(540) - 1
    f["hh20"] = hi.shift(1).rolling(20).max()
    f["tbs"] = b["tb"] / b["volume"]                                   # taker-buy share of this 4h bar
    f["tbs12"] = b["tb"].rolling(3).sum() / b["volume"].rolling(3).sum()
    f["vol"] = b["volume"]
    f["atrp"] = f["atr"] / c
    ft = f.set_index("t")
    # ---- funding: last settlement strictly before t, at most 9 h old
    fu = te_funding(sym)
    fu = fu[fu.index < until]
    idx = fu.index.searchsorted(ft.index, side="left") - 1
    last_t = pd.Series(fu.index[np.clip(idx, 0, None)], index=ft.index).where(idx >= 0)
    val = pd.Series(fu.values[np.clip(idx, 0, None)], index=ft.index).where(idx >= 0)
    fresh = (ft.index.to_series() - last_t) <= pd.Timedelta(hours=9)
    ft["funding"] = val.where(fresh)
    fpct = _trail_pct(fu, 365)                                         # percentile of each settlement in its past year
    ft["funding_pct"] = pd.Series(fpct.values[np.clip(idx, 0, None)], index=ft.index).where(fresh & (idx >= 0))
    # ---- open interest: hours that closed >= 1 h before t
    oi = clean_oi(sym)
    oi = oi[oi.index + pd.Timedelta(hours=2) <= until]
    known = ft.index - pd.Timedelta(hours=2)                           # latest usable open_time
    j = oi.index.searchsorted(known, side="right") - 1
    j8 = oi.index.searchsorted(known - pd.Timedelta(hours=8), side="right") - 1
    ok = (j >= 0) & (j8 >= 0)
    oi_now = pd.Series(np.where(ok, oi.values[np.clip(j, 0, None)], np.nan), index=ft.index)
    oi_8 = pd.Series(np.where(ok, oi.values[np.clip(j8, 0, None)], np.nan), index=ft.index)
    stale = (known - oi.index[np.clip(j, 0, None)]) > pd.Timedelta(hours=3)
    ft["doi8"] = (oi_now / oi_8 - 1).where(~stale)
    # ---- trailing percentiles of the 4h series (each window ends at t)
    for col, days in (("doi8", 90), ("tbs12", 90), ("tbs", 90), ("ret24", 365), ("ret8", 90), ("vol", 90), ("atrp", 180)):
        ft[col + "_pct"] = _trail_pct(ft[col].dropna(), days).reindex(ft.index)
    # ---- market regime known at t (trailing 90 days of price)
    ft["regime"] = np.select([ft["ret90d"] > 0.15, ft["ret90d"] < -0.15], ["up", "down"], "range")
    ft.loc[ft["ret90d"].isna(), "regime"] = "unknown"
    return ft.reset_index().iloc[1100:]                                # warm-up (180-day percentiles)


# ---- hypotheses: (signal, price-only ablation of the same rule) ---------------------------------------------------
def signal(f: pd.DataFrame, hyp: str, q: float, ablation: bool = False) -> pd.Series:
    if hyp == "H1":   # crowded shorts: funding in the bottom q of its past year after a 24h fall
        core = f["ret24"] < 0
        return core & (f["ret24_pct"] <= q if ablation else f["funding_pct"] <= q)
    if hyp == "H2":   # forced deleveraging: open interest collapses with a sharp price drop
        core = f["ret8"] <= -1.0 * f["atrp"]
        return core & (f["ret8_pct"] <= q if ablation else f["doi8_pct"] <= q)
    if hyp == "H3":   # absorption: aggressive selling (low taker-buy share) yet price did not fall over 12h
        core = f["ret12"] >= 0
        return core & (f["vol_pct"] >= 1 - q if ablation else f["tbs12_pct"] <= q)
    if hyp == "H4":   # compression breakout confirmed by aggressive buying
        core = (f["atrp_pct"] <= 0.20) & (f["close"] > f["hh20"])
        return core if ablation else core & (f["tbs_pct"] >= 1 - q)
    raise ValueError(hyp)


def configs() -> list[dict]:
    # H4 (compression breakout + aggressive buying) was drafted and dropped before any outcome was computed:
    # signal counts alone (≤ 54 bars in 3.9 years per asset) give too few trades for the ≥ 40-fill rule, and it
    # overlaps te-0.1.0 family B. Thresholds below were set from signal COUNTS only (no returns were looked at).
    qs = {"H1": (0.10, 0.05), "H2": (0.10, 0.05), "H3": (0.10, 0.05)}
    return [{"id": f"{h}_q{q}_{e}", "hyp": h, "q": q, "exit": e} for h in qs for q, e in itertools.product(qs[h], EXITS)]


def order_at(row, cfg: dict) -> Order | None:
    e = EXITS[cfg["exit"]]
    lim = row["close"] - ENTRY_K * row["atr"]
    stop, target = lim - e["m"] * row["atr"], lim + e["tp_atr"] * row["atr"]
    if not (0 < stop < lim < target):
        return None
    return Order(row["t"], target=float(target), stop=float(stop), limit=float(lim), entry_bars=ENTRY_BARS, hold_bars=e["hold"])
