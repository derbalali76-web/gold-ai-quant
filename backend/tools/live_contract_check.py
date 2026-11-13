"""Run on YOUR machine (internet required): verifies every free source against its parser and writes
data/verification.json. Providers stay `verified=False` in reports until this passes.

    set TWELVEDATA_API_KEY=...   (Windows)   |   export TWELVEDATA_API_KEY=...   (Linux/Mac)
    python tools/live_contract_check.py
"""
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from goldquant.providers.history import HistoryStore  # noqa: E402
from goldquant.providers.twelvedata import TwelveDataProvider  # noqa: E402
from goldquant.providers.xaus import XausSpot  # noqa: E402
from goldquant.sources.cftc import CftcSource  # noqa: E402
from goldquant.sources.fred import FredSource  # noqa: E402
from goldquant.sources.news import NewsSource  # noqa: E402

OUT = Path(os.environ.get("GOLDQUANT_DATA_DIR", Path(__file__).resolve().parents[1] / "data")) / "verification.json"


def check(name, fn):
    t0 = datetime.now(timezone.utc)
    try:
        detail = fn()
        print(f"[OK]   {name}: {detail}")
        return {"source": name, "ok": True, "detail": detail, "at": t0.isoformat()}
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {name}: {exc}")
        return {"source": name, "ok": False, "error": str(exc)[:300], "trace": traceback.format_exc()[-600:], "at": t0.isoformat()}


def main():
    now = datetime.now(timezone.utc)
    res = []
    key = os.environ.get("TWELVEDATA_API_KEY", "")
    if key:
        td = TwelveDataProvider(key, HistoryStore())

        def td_quote():
            q = td.quote(now)
            assert q is not None, td.last_error
            age = (now - q.observed_at).total_seconds()
            return f"price={q.price} observed_at={q.observed_at.isoformat()} age_s={age:.0f}"

        def td_bars():
            b = td.bars("M15", now, 500)
            assert b is not None and len(b.df) > 100, td.last_error
            b.validate()
            return f"M15 bars={len(b.df)} last={b.df.index[-1].isoformat()}"
        res += [check("TwelveData quote", td_quote), check("TwelveData M15 bars", td_bars)]
    else:
        res.append({"source": "TwelveData", "ok": False, "error": "TWELVEDATA_API_KEY not set"})

    def xa():
        x = XausSpot()
        q = x.quote()
        assert q is not None, x.last_error
        return f"price={q.price} updated_at={q.observed_at.isoformat()}"
    res.append(check("xaus.com spot", xa))
    res.append(check("FRED DFII10", lambda: f"{len(FredSource().fetch('DFII10', '2024-01-01'))} rows"))
    res.append(check("CFTC COT gold", lambda: f"{len(CftcSource().fetch(52))} weeks"))

    def news():
        ns = NewsSource()
        items = ns.fetch_all()
        assert items, ns.errors
        return f"{len(items)} items; errors={ns.errors}"
    res.append(check("Official RSS", news))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"ran_at": now.isoformat(), "results": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwritten {OUT}")
    sys.exit(0 if all(r["ok"] for r in res) else 1)


if __name__ == "__main__":
    main()
