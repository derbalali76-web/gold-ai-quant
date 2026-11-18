"""Trade-engine-only data collector (te-0.2.0). Writes ONLY under trade_engine/data/ — the shared market_data store
and the collectors of the other engines are not touched.

Funding (USD-M perpetual) from the public Binance archive, one file per month, every month including December
(the shared collector misses Decembers: it skips a year file once it holds >= 1 000 rows, and December is only
published after the year ends). Each month is fetched again until it is complete and its archive no longer changes.

Point in time: a funding rate is fixed and published by the exchange at its settlement time (calc_time); the
archive file is a later copy of the same values. The engine therefore treats a rate as known strictly after its
calc_time, which is what a live system reading the exchange API would see.

Run (GitHub Actions; the sandbox cannot reach Binance): python -m trade_engine.collect
"""
from __future__ import annotations
import csv, hashlib, io, json, sys, time, urllib.request, zipfile
from datetime import date, datetime, timezone
from pathlib import Path

BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
DATA = Path(__file__).resolve().parent / "data"
START = {"BTCUSDT": (2020, 1), "SOLUSDT": (2020, 9), "ETHUSDT": (2020, 1)}


def months(y: int, m: int, end: tuple[int, int]):
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fetch(url: str) -> bytes | None:
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ai-quant-te"}), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            pass
        time.sleep(2 * (k + 1))
    raise RuntimeError(f"fetch failed: {url}")


def parse(blob: bytes) -> list[tuple[int, float]]:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0]).decode("utf-8")
    rows = list(csv.reader(io.StringIO(raw)))
    head = [c.strip().lower() for c in rows[0]]
    has_head = not head[0].isdigit()
    ti = head.index("calc_time") if has_head and "calc_time" in head else 0
    ri = head.index("last_funding_rate") if has_head and "last_funding_rate" in head else len(head) - 1
    out = {}
    for r in rows[1 if has_head else 0:]:
        if r and r[ti].strip():
            out[int(r[ti])] = float(r[ri])           # duplicate calc_time -> one row (last wins)
    return sorted(out.items())


def main(argv) -> int:
    today = datetime.now(timezone.utc).date()
    last_full = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    man_p = DATA / "manifest.json"
    man = json.loads(man_p.read_text()) if man_p.exists() else {}
    for sym, (y0, m0) in START.items():
        for y, m in months(y0, m0, last_full):
            key = f"{sym}/{y:04d}-{m:02d}"
            ent = man.get(key)
            if ent and ent.get("final"):
                continue
            url = f"{BASE}/{sym}/{sym}-fundingRate-{y:04d}-{m:02d}.zip"
            blob = fetch(url)
            if blob is None:
                man[key] = {"url": url, "status": "not_published", "checked": today.isoformat()}
                continue
            rows = parse(blob)
            p = DATA / sym / "funding" / f"{y:04d}-{m:02d}.csv"
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["calc_time_ms", "calc_time_utc", "funding"])
                for t, v in rows:
                    w.writerow([t, datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", repr(v)])
            sha = hashlib.sha256(blob).hexdigest()
            # a month is final once fetched at least 7 days after it ended and unchanged since the previous fetch
            ended_days = (today - (date(y + (m == 12), m % 12 + 1, 1))).days
            final = bool(ent and ent.get("zip_sha256") == sha and ended_days >= 7)
            man[key] = {"url": url, "zip_sha256": sha, "rows": len(rows), "fetched": today.isoformat(), "final": final}
            print(key, len(rows), "final" if final else "", flush=True)
    man_p.parent.mkdir(parents=True, exist_ok=True)
    man_p.write_text(json.dumps(dict(sorted(man.items())), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
