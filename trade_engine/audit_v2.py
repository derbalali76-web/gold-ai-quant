"""te-0.2.0 data audit: completeness, timestamps, duplicates, agreement with the shared store, publication timing.
Reads data only (no prices are turned into returns). Output: trade_engine/reports/audit_v2.json
Run: python -m trade_engine.audit_v2
"""
from __future__ import annotations
import calendar, glob, json
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent / "market_data" / "crypto"


def te_funding(sym: str) -> pd.DataFrame:
    parts = [pd.read_csv(f) for f in sorted(glob.glob(str(HERE / "data" / sym / "funding" / "*.csv")))]
    df = pd.concat(parts)
    df["t"] = pd.to_datetime(df["calc_time_ms"], unit="ms", utc=True)
    return df.set_index("t").sort_index()


def shared_funding(sym: str) -> pd.Series:
    df = pd.concat([pd.read_csv(f, compression="gzip") for f in sorted(glob.glob(str(SHARED / sym / "funding" / "*.csv.gz")))])
    c = df.columns[0]
    df[c] = pd.to_datetime(df[c], utc=True, format="ISO8601")
    return df.set_index(c)["funding"].sort_index()


def funding_audit(sym: str) -> dict:
    f = te_funding(sym)
    dup = int(f.index.duplicated().sum())
    gaps = f.index.to_series().diff().dropna()
    by_month = f.groupby(f.index.strftime("%Y-%m")).size()
    months = []
    for k, n in by_month.items():
        y, m = map(int, k.split("-"))
        exp = calendar.monthrange(y, m)[1] * 3
        if n < exp:
            months.append({"month": k, "rows": int(n), "expected_8h": exp})
    sh = shared_funding(sym)
    # match on the settlement second (the shared store rounds to ms the same way)
    a = f["funding"].copy(); a.index = a.index.floor("s")
    b = sh.copy(); b.index = b.index.floor("s")
    both = a.index.intersection(b.index)
    diff = (a.loc[both] - b.loc[both]).abs()
    dec = f[f.index.month == 12]
    off = f.index[(f.index.minute != 0) | (f.index.second != 0)]
    return {"first": str(f.index[0]), "last": str(f.index[-1]), "rows": len(f), "duplicates": dup,
            "monotonic": bool(f.index.is_monotonic_increasing), "max_gap_hours": round(gaps.max().total_seconds() / 3600, 2),
            "interval_hours_counts": {str(k): int(v) for k, v in (gaps.dt.total_seconds() / 3600).round(2).value_counts().items()},
            "months_below_3_per_day": months, "december_rows": int(len(dec)),
            "december_months": sorted(set(dec.index.strftime("%Y-%m"))),
            "settlements_off_the_hour": int(len(off)), "max_offset_seconds": float(max([(t - t.floor("h")).total_seconds() for t in off], default=0)),
            "shared_store_overlap": int(len(both)), "shared_store_max_abs_diff": float(diff.max()) if len(both) else None,
            "shared_store_rows_missing_here": int(len(b.index.difference(a.index)))}


def metrics_audit(sym: str) -> dict:
    df = pd.concat([pd.read_csv(f, compression="gzip") for f in sorted(glob.glob(str(SHARED / sym / "metrics" / "*.csv.gz")))])
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True, format="ISO8601")
    dup = int(df["open_time"].duplicated().sum())
    s = df.drop_duplicates("open_time").set_index("open_time").sort_index()["oi"]
    full = pd.date_range(s.index[0], s.index[-1], freq="h")
    miss = full.difference(s.index)
    jumps = (s.pct_change().abs() > 0.5).sum()
    return {"first": str(s.index[0]), "last": str(s.index[-1]), "hours": len(s), "missing_hours": len(miss),
            "missing_list": [str(x) for x in miss[:20]], "duplicates": dup, "oi_nan": int(s.isna().sum()),
            "oi_jumps_over_50pct_in_1h": int(jumps)}


def main() -> int:
    out = {"funding_te_store": {s: funding_audit(s) for s in ("BTCUSDT", "SOLUSDT")},
           "open_interest_shared_store": {s: metrics_audit(s) for s in ("BTCUSDT", "SOLUSDT")},
           "publication_rules": {
               "spot_klines": "bar values final at bar close; used when close <= t",
               "funding": "rate fixed and published at settlement (calc_time); used when calc_time < t (strict); stale after 9 h",
               "open_interest": "5-min snapshot published by the exchange API within minutes; hourly row = last snapshot of the hour; used when open_time + 2 h <= t (1 h safety lag)",
               "archive_files": "monthly/daily archive copies appear later but carry the same values; the backtest uses event time + the lags above, which a live reader of the API can also meet"}}
    p = HERE / "reports" / "audit_v2.json"
    p.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
