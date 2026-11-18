"""AI QUANT Trade Engine — data layer (read-only over market_data/crypto). Stdlib + pandas only.

1h and 15m Binance spot bars are stored per month. 4h bars are built from 1h bars on the UTC grid
00/04/08/12/16/20; a 4h bar is kept only when all four hourly bars exist (no silent gap filling)."""
from __future__ import annotations
import gzip, hashlib, io
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1] / "market_data" / "crypto"


def load(symbol: str, tf: str) -> pd.DataFrame:
    parts = []
    for f in sorted((ROOT / symbol / tf).glob("*.csv.gz")):
        parts.append(pd.read_csv(f, compression="gzip"))
    df = pd.concat(parts, ignore_index=True)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True, format="ISO8601")
    df = df.drop_duplicates("open_time").sort_values("open_time").set_index("open_time")
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def to_4h(h1: pd.DataFrame) -> pd.DataFrame:
    g = h1.groupby(h1.index.floor("4h"))
    out = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
                volume=("volume", "sum"), n=("close", "size"))
    return out[out["n"] == 4].drop(columns="n")


def fingerprint(symbol: str, tf: str) -> str:
    """sha256 over the stored monthly files (bytes), so every run names the exact data it used."""
    h = hashlib.sha256()
    for f in sorted((ROOT / symbol / tf).glob("*.csv.gz")):
        h.update(f.name.encode()); h.update(f.read_bytes())
    return h.hexdigest()[:16]


def audit(symbol: str, tf: str) -> dict:
    df = load(symbol, tf)
    step = pd.Timedelta(tf.replace("m", "min"))
    full = pd.date_range(df.index[0], df.index[-1], freq=step)
    missing = full.difference(df.index)
    bad = int(((df["high"] < df[["open", "close"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1))
               | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)).sum())
    ret = df["close"].pct_change().abs()
    gaps = pd.Series(missing).diff().ne(step).cumsum() if len(missing) else pd.Series(dtype=int)
    longest = int(gaps.value_counts().max()) if len(missing) else 0
    return {"symbol": symbol, "tf": tf, "first": str(df.index[0]), "last": str(df.index[-1]), "bars": len(df),
            "expected": len(full), "missing": len(missing), "missing_pct": round(100 * len(missing) / len(full), 3),
            "longest_gap_bars": longest, "bad_ohlc": bad, "zero_volume": int((df["volume"] == 0).sum()),
            "moves_over_15pct": int((ret > 0.15).sum()), "sha": fingerprint(symbol, tf)}


if __name__ == "__main__":
    import json
    rows = []
    for s in ("BTCUSDT", "SOLUSDT"):
        for tf in ("1h", "15m"):
            rows.append(audit(s, tf))
        h4 = to_4h(load(s, "1h"))
        rows.append({"symbol": s, "tf": "4h(built)", "first": str(h4.index[0]), "last": str(h4.index[-1]), "bars": len(h4)})
    print(json.dumps(rows, indent=1))
