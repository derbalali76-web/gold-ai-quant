"""Cloud mode: market data and trained models live in a (private) GitHub repository.

* A GitHub Actions job (2 vCPU, free minutes) collects data hourly and retrains/validates models every few
  hours, committing compact monthly CSV files and model artifacts.
* The free web service (small CPU, sleeps when idle) only downloads the latest snapshot and PREDICTS —
  no heavy training on the request path, so a cold start stays within the app's timeout.

Layout inside the repository:
    market_data/bars/{provider}/{symbol}/{tf}/{YYYY-MM}.csv.gz
    market_data/obs/{source}__{series}.csv.gz
    models/path_state.pkl   (+ models/manifest.json)
"""
from __future__ import annotations

import gzip
import io
import json
import os
import pickle
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .providers.history import HistoryStore
from .providers.http import HttpClient


# ---------------- export (collector side)
def export_bars(history: HistoryStore, root: Path, provider: str, symbol: str, tf: str) -> int:
    df = history.load_bars(provider, symbol, tf, limit=10_000_000)
    if df.empty:
        return 0
    d = root / "bars" / provider / symbol.replace("/", "") / tf
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for period, part in df.groupby(df.index.strftime("%Y-%m")):
        p = d / f"{period}.csv.gz"
        if p.exists():
            old = read_bars_file(p)
            part = pd.concat([old, part])
            part = part[~part.index.duplicated(keep="last")].sort_index()
        # deterministic gzip (no timestamp) and no rewrite when unchanged: commits only touch months that changed
        raw = gzip.compress(part.to_csv(index_label="open_time", float_format="%.5f").encode("utf-8"), mtime=0)
        if not (p.exists() and p.read_bytes() == raw):
            p.write_bytes(raw)
        n += len(part)
    return n


def read_bars_file(p: Path) -> pd.DataFrame:
    df = pd.read_csv(p, compression="gzip", index_col="open_time")
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def export_observations(history: HistoryStore, root: Path, source: str, series: str) -> int:
    df = history.load_observations_as_of(source, series, datetime(2100, 1, 1, tzinfo=timezone.utc))
    if df.empty:
        return 0
    d = root / "obs"
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / f"{source}__{series}.csv.gz", "wt", encoding="utf-8") as f:
        df.to_csv(f, index=False)
    return len(df)


# ---------------- import (server side)
def import_tree(history: HistoryStore, root: Path) -> dict:
    counts = {}
    bars = root / "bars"
    if bars.exists():
        for f in sorted(bars.glob("*/*/*/*.csv.gz")):
            provider, symbol, tf = f.parts[-4], f.parts[-3], f.parts[-2]
            sym = "XAU/USD" if symbol == "XAUUSD" and provider == "TwelveData" else symbol
            history.upsert_bars(provider, sym, tf, read_bars_file(f), datetime.now(timezone.utc))
            counts[f"{provider}:{sym}:{tf}"] = counts.get(f"{provider}:{sym}:{tf}", 0) + 1
    obs = root / "obs"
    if obs.exists():
        for f in obs.glob("*.csv.gz"):
            source, series = f.name[:-len(".csv.gz")].split("__", 1)
            df = pd.read_csv(f, compression="gzip")
            rows = [{"observed_at": r.observed_at, "published_at": r.published_at, "fetched_at": r.published_at,
                     "value": float(r.value)} for r in df.itertuples()]
            history.upsert_observations(source, series, rows)
            counts[f"obs:{source}:{series}"] = len(rows)
    return counts


def download_repo(repo: str, token: str, dest: Path, http: HttpClient | None = None, ref: str = "main") -> Path:
    """Fetch the repository snapshot (GitHub REST tarball) and extract only market_data/, models/ and config/."""
    import httpx
    url = f"https://api.github.com/repos/{repo}/tarball/{ref}"
    head = {"Accept": "application/vnd.github+json"}
    r = httpx.get(url, follow_redirects=True, timeout=60, headers=dict(head, Authorization=f"Bearer {token}") if token else head)
    if token and getattr(r, "status_code", 200) in (401, 403):  # expired / revoked token: a public repository still downloads
        r = httpx.get(url, follow_redirects=True, timeout=60, headers=head)
    r.raise_for_status()
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as tar:
        for m in tar.getmembers():
            parts = Path(m.name).parts
            if len(parts) < 2 or parts[1] not in ("market_data", "models", "config") or not (m.isfile() or m.isdir()):
                continue
            target = dest.joinpath(*parts[1:]).resolve()
            if not str(target).startswith(str(dest.resolve())):
                continue  # path traversal guard
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(m).read())
    return dest


# ---------------- model artifacts
def save_path_state(state, root: Path, meta: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "path_state.pkl").write_bytes(pickle.dumps(state))
    (root / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def load_path_state(root: Path):
    """Artifacts come only from the user's own private repository (written by their own CI job)."""
    p = root / "path_state.pkl"
    if not p.exists():
        return None, None
    meta = json.loads((root / "manifest.json").read_text(encoding="utf-8")) if (root / "manifest.json").exists() else {}
    return pickle.loads(p.read_bytes()), meta


DEFAULT_REPO = "derbalali76-web/gold-ai-quant"  # public: models and data download without a token


def cloud_settings() -> dict:
    # On Render (RENDER=true is set by the platform) the public repository is the default source;
    # locally and in tests nothing is downloaded unless GOLDQUANT_DATA_REPO is set explicitly.
    return {"repo": os.environ.get("GOLDQUANT_DATA_REPO", "").strip() or (DEFAULT_REPO if os.environ.get("RENDER") else ""),
            "token": os.environ.get("GOLDQUANT_REPO_TOKEN", "").strip()}
