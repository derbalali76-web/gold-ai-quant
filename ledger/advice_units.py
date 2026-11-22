#!/usr/bin/env python3
"""advice-units-0.1 — does selling BEFORE a support breaks, then buying back, leave the holder with more units?

PRE-REGISTERED 2026-11-22 (owner request), before any result of this study was computed. It studies the
SELL_NOW instructions that advice-0.1.0 records for holders; advice-0.1.0 itself, its records and its own verdict
are not changed. Forecast quality (was the likely side right?) and trading results (units) are reported apart.

Population: every ADVICE record with hold.advice == SELL_NOW and a HOURS support (hours.down[0]), scored once its
168 hours of closed H1 bars exist. One record = one market signal (never counted twice).

Three policies for a holder of 1 unit, same window, same costs (`cost` of the record = one round trip in price
units; each buy or sell pays cost / 2), fills as in advice-0.1.0 (a limit fills at its level or at a better open; a
protective buy-back fills at its level or a worse open; a bar touching both counts as the worse case):
  HOLD         keep the unit: 1.0 unit.
  PRE_EMPTIVE  advice-0.1.0 as recorded: sell at the record price p0; buy back at `at` (hold.at) when reached, or
               above `exit` (hold.exit) when price rises there first (protection). Never bought back: units valued
               at the window's last close (cash / close_end, no fee) and flagged NO_REBUY.
  AFTER_BREAK  wait for the first H1 CLOSE below the support S = hours.down[0]; sell at the next bar's open; then
               the same buy-back rules (at `at` if below the sale price, protection above `exit`). No break in the
               window: it simply held (1.0 unit).
Metric: units gain = units_end / 1 − 1, in percent, after all fees. Also kept per record: max price after the sale
relative to p0, whether the buy-back level was ever reached, and ROSE_NO_RETURN = the price went above p0 after
the sale and never came back to the buy-back level within the window (the case the owner asked to see).

Verdict (shown only with n >= 20 scored records; daily records overlap, the count of non-overlapping weeks is
reported beside n; nothing is called proven before an independent forward check):
  PRE_EMPTIVE is USEFUL when its mean units gain vs HOLD > 0 AND it beat HOLD in >= 50 % of records AND its mean
  is above AFTER_BREAK's mean; otherwise NOT_USEFUL. AFTER_BREAK vs HOLD is reported the same way.
Standard library only.
"""
from __future__ import annotations

from typing import Optional

VERSION = "advice-units-0.1"
MIN_N = 20


def _buyback(bars: list, cash: float, at: Optional[float], ex: Optional[float], fee: float):
    """Buy back from `cash` at `at` (limit below) or above `ex` (protection). Returns (units|None, how, price)."""
    for b in bars:
        tl = at is not None and b[3] <= at
        th = ex is not None and b[2] >= ex
        if th:                                   # protection first when both (worse case)
            px = max(ex, b[1])
            return cash / (px + fee), "PROTECTION", px
        if tl:
            px = min(at, b[1])
            return cash / (px + fee), "BOUGHT_BACK", px
    return None, "NO_REBUY", None


def score(rec: dict, window: list) -> dict | None:
    """rec: ADVICE data (hold, hours, price_at_record, cost). window: closed H1 bars [t, o, h, l, c] after recording."""
    h = rec.get("hold") or {}
    down = (rec.get("hours") or {}).get("down")
    if h.get("advice") != "SELL_NOW" or not down or not window:
        return None
    p0, fee, at, ex, sup = rec["price_at_record"], rec["cost"] / 2, h.get("at"), h.get("exit"), down[0]
    end = window[-1][4]
    out = {"version": VERSION, "p0": p0, "close_end": end, "support": sup, "rebuy_at": at, "protect_above": ex}
    # PRE_EMPTIVE
    cash = p0 - fee
    u, how, px = _buyback(window, cash, at, ex, fee)
    reached = any(b[3] <= at for b in window) if at is not None else False
    max_after = max(b[2] for b in window)
    units = u if u is not None else cash / end
    out["pre_emptive"] = {"how": how, "price": px, "units": round(units, 6), "gain_pct": round((units - 1) * 100, 4),
                          "rebuy_reached": reached, "max_after_pct": round((max_after / p0 - 1) * 100, 4),
                          "rose_no_return": bool(max_after > p0 and not reached)}
    # AFTER_BREAK
    k = next((i for i, b in enumerate(window) if b[4] < sup), None)
    if k is None or k + 1 >= len(window):
        out["after_break"] = {"how": "NO_BREAK", "units": 1.0, "gain_pct": 0.0}
    else:
        s = window[k + 1][1]
        cash2 = s - fee
        rest = window[k + 1:]
        u2, how2, px2 = _buyback(rest, cash2, at if (at is not None and at < s) else None, ex, fee)
        units2 = u2 if u2 is not None else cash2 / end
        out["after_break"] = {"how": how2, "sold_at": s, "price": px2, "units": round(units2, 6), "gain_pct": round((units2 - 1) * 100, 4)}
    out["hold"] = {"units": 1.0, "gain_pct": 0.0}
    return out


def stats(rows: list[dict]) -> dict:
    """rows: [{date, asset, result}] of scored records."""
    n = len(rows)
    out = {"version": VERSION, "min_n": MIN_N, "n": n}
    if not n:
        return out
    from datetime import datetime, timedelta
    days, weeks, last = sorted(datetime.fromisoformat(r["date"]) for r in rows), 0, None
    for d in days:
        if last is None or d - last >= timedelta(days=7):
            weeks, last = weeks + 1, d
    out["independent_weeks"] = weeks
    for pol in ("pre_emptive", "after_break"):
        g = [r["result"][pol]["gain_pct"] for r in rows]
        out[pol] = {"mean_gain_pct": round(sum(g) / n, 4), "beat_hold_rate": round(sum(x > 0 for x in g) / n, 4)}
    pe = out["pre_emptive"]
    pe["no_rebuy"] = sum(r["result"]["pre_emptive"]["how"] == "NO_REBUY" for r in rows)
    pe["rose_no_return"] = sum(r["result"]["pre_emptive"]["rose_no_return"] for r in rows)
    pe["protection_exits"] = sum(r["result"]["pre_emptive"]["how"] == "PROTECTION" for r in rows)
    if n >= MIN_N:
        ok = pe["mean_gain_pct"] > 0 and pe["beat_hold_rate"] >= 0.5 and pe["mean_gain_pct"] > out["after_break"]["mean_gain_pct"]
        pe["verdict"] = "USEFUL" if ok else "NOT_USEFUL"
        ab = out["after_break"]
        ab["verdict"] = "USEFUL" if (ab["mean_gain_pct"] > 0 and ab["beat_hold_rate"] >= 0.5) else "NOT_USEFUL"
    return out


# ------------------------------------------------------------------------------- runner (inside record.sh)
BARS = {"XAU": "bars_H1.json", "BTC": "bars_BTC_H1.json", "ETH": "bars_ETH_H1.json", "SOL": "bars_SOL_H1.json"}


def _chain(path):
    import json
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def run(repo, now):
    """Score every SELL_NOW record whose 168 h window is complete, once, into studies/advice_units.jsonl (own chain)."""
    import hashlib
    import json
    from datetime import datetime, timedelta
    from pathlib import Path
    repo = Path(repo)
    p = repo / "studies" / "advice_units.jsonl"
    lines = _chain(p)
    canon = lambda x: json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)  # noqa: E731
    prev = "0" * 64
    for i, e in enumerate(lines, 1):
        if e.get("seq") != i or e.get("prev") != prev or e["hash"] != hashlib.sha256((prev + canon({k: v for k, v in e.items() if k != "hash"})).encode()).hexdigest():
            raise RuntimeError("studies/advice_units.jsonl chain broken")
        prev = e["hash"]
    done = {e["data"]["ref"] for e in lines}
    ts = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
    led = repo / "ledger.jsonl"
    for line in (led.read_text().splitlines() if led.exists() else []):
        if '"ADVICE"' not in line or '"SELL_NOW"' not in line:
            continue
        e = json.loads(line)
        if e["kind"] != "ADVICE" or e["seq"] in done or e["data"]["hold"]["advice"] != "SELL_NOW":
            continue
        d, rec = e["data"], ts(e["recorded_at"])
        exp = ts(d["expires"])
        f = repo / BARS.get(d["asset"], "-")
        if now < exp + timedelta(hours=1) or not f.exists():
            continue
        bars = [b for b in json.loads(f.read_text()) if ts(b[0]) >= rec and ts(b[0]) < exp and ts(b[0]) + timedelta(hours=1) <= now]
        r = score(d, bars) if bars else None
        data = {"ref": e["seq"], "asset": d["asset"], "date": d["date"], "bars": len(bars),
                "outcome": "SCORED" if r else "NO_DATA", "result": r}
        prev = lines[-1]["hash"] if lines else "0" * 64
        x = {"seq": len(lines) + 1, "kind": "ADVICE_UNITS", "recorded_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": data, "prev": prev}
        x["hash"] = hashlib.sha256((prev + canon({k: v for k, v in x.items() if k != "hash"})).encode()).hexdigest()
        lines.append(x)
        p.parent.mkdir(exist_ok=True)
        with p.open("a") as fh:
            fh.write(canon(x) + "\n")
    rows = [{"date": e["data"]["date"], "asset": e["data"]["asset"], "result": e["data"]["result"]}
            for e in lines if e["data"]["outcome"] == "SCORED"]
    st = stats(rows)
    st["by_asset"] = {a: stats([r for r in rows if r["asset"] == a]) for a in sorted({r["asset"] for r in rows})}
    (repo / "studies").mkdir(exist_ok=True)
    (repo / "studies" / "advice_units_stats.json").write_text(json.dumps(st, indent=1) + "\n")
    return st


if __name__ == "__main__":
    import sys
    from datetime import datetime, timezone
    try:
        s = run(sys.argv[1] if len(sys.argv) > 1 else ".", datetime.now(timezone.utc))
        print("advice units:", s.get("n"), "scored")
    except Exception as e:  # noqa: BLE001  (never blocks the range ledger)
        print("advice units failed:", e)
