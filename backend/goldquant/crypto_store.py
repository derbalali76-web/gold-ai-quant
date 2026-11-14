"""Crypto history in the data repository: market_data/crypto/{SYMBOL}/{tf}/{YYYY-MM}.csv.gz (OHLC + real volume +
taker-buy volume) and market_data/crypto/{SYMBOL}/funding/{YYYY}.csv.gz. Deterministic gzip (mtime=0) so unchanged
months do not create commits."""
from __future__ import annotations

import gzip
import io
from pathlib import Path

import pandas as pd

COLS = ["open", "high", "low", "close", "volume", "taker_buy_volume"]


def _write(path: Path, df: pd.DataFrame) -> bool:
    buf = io.StringIO()
    df.to_csv(buf, float_format="%.8g")
    data = buf.getvalue().encode("utf-8")
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as g:
        g.write(data)
    blob = out.getvalue()
    if path.exists() and path.read_bytes() == blob:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    return True


def save_bars(root: Path, symbol: str, tf: str, df: pd.DataFrame) -> int:
    """Merge df into the monthly files; returns files written."""
    if df is None or df.empty:
        return 0
    n = 0
    for key, part in df.groupby(df.index.strftime("%Y-%m")):
        p = root / "crypto" / symbol / tf / f"{key}.csv.gz"
        if p.exists():
            old = read(p)
            part = pd.concat([old, part])
            part = part[~part.index.duplicated(keep="last")]
        n += _write(p, part.sort_index()[[c for c in COLS if c in part.columns]])
    return n


def read(p: Path) -> pd.DataFrame:
    df = pd.read_csv(p, compression="gzip", index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "open_time"
    return df


def load_bars(root: Path, symbol: str, tf: str) -> pd.DataFrame:
    files = sorted((root / "crypto" / symbol / tf).glob("*.csv.gz"))
    if not files:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(read(f) for f in files)
    return df[~df.index.duplicated(keep="last")].sort_index()


def have_month(root: Path, symbol: str, tf: str, y: int, m: int, min_rows: int) -> bool:
    p = root / "crypto" / symbol / tf / f"{y:04d}-{m:02d}.csv.gz"
    return p.exists() and len(read(p)) >= min_rows


def save_funding(root: Path, symbol: str, df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    n = 0
    for key, part in df.groupby(df.index.strftime("%Y")):
        p = root / "crypto" / symbol / "funding" / f"{key}.csv.gz"
        if p.exists():
            part = pd.concat([read(p), part])
            part = part[~part.index.duplicated(keep="last")]
        n += _write(p, part.sort_index())
    return n


def load_funding(root: Path, symbol: str) -> pd.DataFrame:
    files = sorted((root / "crypto" / symbol / "funding").glob("*.csv.gz"))
    if not files:
        return pd.DataFrame(columns=["funding"])
    df = pd.concat(read(f) for f in files)
    return df[~df.index.duplicated(keep="last")].sort_index()


def save_metrics(root: Path, symbol: str, df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    n = 0
    for key, part in df.groupby(df.index.strftime("%Y-%m")):
        p = root / "crypto" / symbol / "metrics" / f"{key}.csv.gz"
        if p.exists():
            part = pd.concat([read(p), part])
            part = part[~part.index.duplicated(keep="last")]
        n += _write(p, part.sort_index())
    return n


def load_metrics(root: Path, symbol: str) -> pd.DataFrame:
    files = sorted((root / "crypto" / symbol / "metrics").glob("*.csv.gz"))
    if not files:
        return pd.DataFrame()
    df = pd.concat(read(f) for f in files)
    return df[~df.index.duplicated(keep="last")].sort_index()


def metrics_days_have(root: Path, symbol: str, y: int, m: int) -> int:
    p = root / "crypto" / symbol / "metrics" / f"{y:04d}-{m:02d}.csv.gz"
    return len(read(p)) if p.exists() else 0
