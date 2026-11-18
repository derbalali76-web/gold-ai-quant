#!/usr/bin/env python3
"""AI QUANT Trade Engine — live paper record of ONE pre-registered rule (te-live-h1-0.1, see PREREG_live.md).

Rule (te-0.2.0 configuration H1_q0.1_E5d, BTCUSDT, unchanged): at each 4h close t (00/04/.../20 UTC)
  signal  <=>  r24 < 0  and  P_365d(funding, t) <= 0.10
  order   :   buy limit L = C_t - 0.25*ATR_t, valid until t + 12 h; stop S = L - 2*ATR_t; target T = L + 3*ATR_t;
              time exit at the close of the 30th 4h bar after the fill's bar. One position at a time.
Inputs known at t only: 1h spot bars that closed <= t (Binance public market data), funding settlements strictly
before t and at most 9 h old (Binance USD-M public funding history). The order is live from the moment it is
RECORDED (not from t): only 15m bars opening at or after the record time can fill or close it.
Fills and exits follow the research simulator exactly (trade_engine/sim.py): a limit fills only when price trades
strictly below it (or opens below it); stop first when both levels are reachable in one 15m bar; no target in the
fill bar; costs 0.10 % maker / taker, 0.01 % half-spread and 0.05 % slippage on stop and time exits.

Every 4h close inside its 75-minute window is recorded as a SCAN line (signal or not), so the record shows every
decision, not only the trades. Files: trade_engine/trades.jsonl (hash-chained, own chain) and
trade_engine/state.json (what the app shows). Standard library only.

usage: te_live.py fetch OUT_DIR            (network: writes OUT_DIR/te_input.json)
       te_live.py update IN_FILE [REPO]    (deterministic: appends lines, writes state.json)
       te_live.py verify [REPO]
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENGINE = "te-live-h1-0.1"
RULE = "te-0.2.0/H1_q0.1_E5d"
SYMBOL = "BTCUSDT"
KLINES = "https://data-api.binance.vision/api/v3/klines"
FUNDING = "https://www.binance.com/fapi/v1/fundingRate"
H, H4, M15 = timedelta(hours=1), timedelta(hours=4), timedelta(minutes=15)
FRESH = timedelta(minutes=75)
Q, ENTRY_K, STOP_M, TP_ATR, ENTRY_BARS, HOLD_BARS = 0.10, 0.25, 2.0, 3.0, 3, 30
COSTS = {"maker": 0.0010, "taker": 0.0010, "half_spread": 0.0001, "slippage": 0.0005}
START = datetime(2026, 11, 18, 16, tzinfo=timezone.utc)  # first decision time of the live record


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def ms(d: datetime) -> int:
    return int(d.timestamp() * 1000)


# ------------------------------------------------------------------------------------------------ fetch (network)
def get_json(url: str, tries: int = 4):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ai-quant-ledger/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url.split('?')[0]}: {err}")


def klines(interval: str, start: datetime, now: datetime) -> list:
    out, cur = {}, ms(start)
    while cur < ms(now):
        rows = get_json(f"{KLINES}?symbol={SYMBOL}&interval={interval}&startTime={cur}&limit=1000")
        if not rows:
            break
        for r in rows:
            out[int(r[0])] = [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), int(r[6])]
        nxt = int(rows[-1][0]) + 1
        if nxt <= cur or len(rows) < 1000:
            break
        cur = nxt
    return [v for k, v in sorted(out.items()) if v[5] < ms(now)]  # closed bars only


def funding(start: datetime, now: datetime) -> list:
    out, cur = {}, ms(start)
    while True:
        rows = get_json(f"{FUNDING}?symbol={SYMBOL}&startTime={cur}&limit=1000")
        for r in rows:
            out[int(r["fundingTime"])] = float(r["fundingRate"])
        if len(rows) < 1000:
            break
        cur = int(rows[-1]["fundingTime"]) + 1
    return [[k, v] for k, v in sorted(out.items()) if k < ms(now)]


def cmd_fetch(out_dir: str, repo: str = ".") -> int:
    now = datetime.now(timezone.utc)
    st = load_state(Path(repo))
    since = now - timedelta(days=2)
    for o in st.get("active", []):
        since = min(since, ts(o["recorded_at"]) - H)
    data = {"fetched_at": iso(now), "h1": klines("1h", now - timedelta(hours=2100), now),
            "m15": klines("15m", since, now), "funding": funding(now - timedelta(days=400), now)}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, "te_input.json").write_text(json.dumps(data))
    print("te fetch:", len(data["h1"]), "h1,", len(data["m15"]), "m15,", len(data["funding"]), "funding")
    return 0


# ---------------------------------------------------------------------------------------------- features at t
def bars4h(h1: list, t: datetime) -> list:
    """4h bars from complete groups of four 1h bars that closed at or before t: [open_ms, o, h, l, c]."""
    groups = {}
    for b in h1:
        if b[0] + 3600_000 <= ms(t):
            g = b[0] - b[0] % (4 * 3600_000)
            groups.setdefault(g, []).append(b)
    out = []
    for g in sorted(groups):
        bs = sorted(groups[g])
        if len(bs) == 4:
            out.append([g, bs[0][1], max(x[2] for x in bs), min(x[3] for x in bs), bs[-1][4]])
    return out


def atr_wilder(b4: list) -> float:
    a, prev = None, None
    for _, o, h, l, c in b4:
        tr = h - l if prev is None else max(h - l, abs(h - prev), abs(l - prev))
        a = tr if a is None else a * (1 - 1 / 14) + tr / 14
        prev = c
    return a


def funding_pct(fu: list, t: datetime):
    """Percentile of the last settlement strictly before t within its trailing 365 days (inclusive)."""
    past = [(k, v) for k, v in fu if k < ms(t)]
    if not past:
        return None, None, None
    k, v = past[-1]
    if ms(t) - k > 9 * 3600_000:
        return None, v, k
    win = [x for kk, x in past if k - 365 * 86400_000 < kk <= k]
    if len(win) < 30:
        return None, v, k
    return sum(1 for x in win if x <= v) / len(win), v, k


def features(inp: dict, t: datetime) -> dict:
    b4 = bars4h(inp["h1"], t)
    if not b4 or b4[-1][0] + 4 * 3600_000 != ms(t):
        return {"ok": False, "reason": "the 4h bar closing at t is incomplete"}
    if len(b4) < 300:
        return {"ok": False, "reason": "not enough history"}
    c = b4[-1][4]
    c24 = next((x[4] for x in b4 if x[0] + 4 * 3600_000 == ms(t - timedelta(hours=24))), None)
    if c24 is None:
        return {"ok": False, "reason": "close 24 h earlier missing"}
    p, f, fk = funding_pct(inp["funding"], t)
    return {"ok": True, "close": c, "atr": atr_wilder(b4), "r24": c / c24 - 1, "funding": f,
            "funding_time": None if fk is None else iso(datetime.fromtimestamp(fk / 1000, timezone.utc)),
            "funding_pct": p}


def signal(fx: dict) -> bool:
    return bool(fx.get("ok") and fx["funding_pct"] is not None and fx["r24"] < 0 and fx["funding_pct"] <= Q)


def order_from(fx: dict, t: datetime) -> dict:
    lim = fx["close"] - ENTRY_K * fx["atr"]
    return {"t": iso(t), "limit": round(lim, 2), "stop": round(lim - STOP_M * fx["atr"], 2),
            "target": round(lim + TP_ATR * fx["atr"], 2), "entry_until": iso(t + ENTRY_BARS * H4), "hold_bars": HOLD_BARS}


# --------------------------------------------------------------------------- resolution (same rules as sim.py)
def simulate(o: dict, m15: list, start: datetime, now: datetime) -> dict:
    """o: order; m15: [open_ms, o, h, l, c, close_ms] closed bars; start: first moment the order is live."""
    bars = [b for b in m15 if b[0] >= ms(start)]
    entry_end = ts(o["entry_until"])
    lim, stop, tgt = o["limit"], o["stop"], o["target"]
    fill_i = entry = None
    for i, b in enumerate(bars):
        if b[0] >= ms(entry_end):
            break
        if b[1] < lim:
            fill_i, entry = i, b[1]
            break
        if b[3] < lim:
            fill_i, entry = i, lim
            break
    if fill_i is None:
        if bars and bars[-1][5] >= ms(entry_end) - 1:
            return {"status": "NOT_FILLED"}
        if ms(now) - ms(entry_end) > 2 * 86400_000:   # bars never arrived: closed as missing data, never guessed
            return {"status": "NO_DATA"}
        return {"status": "PENDING"}
    fb = bars[fill_i]
    fill_t = datetime.fromtimestamp(fb[0] / 1000, timezone.utc)
    hold_end = ms(fill_t) - ms(fill_t) % (4 * 3600_000) + (o["hold_bars"] + 1) * 4 * 3600_000
    life = [b for b in bars[fill_i:] if b[0] < hold_end]
    out = px = j = None
    if entry <= stop:
        out, px, j = "STOP", entry * (1 - COSTS["slippage"]), 0
    elif entry >= tgt:
        out, px, j = "TARGET", entry, 0
    else:
        for i, b in enumerate(life):
            first = i == 0
            if not first and b[1] <= stop:
                out, px, j = "STOP", b[1] * (1 - COSTS["slippage"]), i
                break
            if not first and b[1] > tgt:
                out, px, j = "TARGET", b[1], i
                break
            if b[3] <= stop:
                out, px, j = "STOP", stop * (1 - COSTS["slippage"]), i
                break
            if not first and b[2] > tgt:
                out, px, j = "TARGET", tgt, i
                break
    res = {"fill_time": iso(fill_t), "entry": round(entry, 2)}
    if out is None:
        complete = bool(life) and life[-1][5] >= hold_end - 1
        if not complete:
            if ms(now) - hold_end > 2 * 86400_000:
                return dict(res, status="NO_DATA")
            return dict(res, status="OPEN")
        out, j = "TIME", len(life) - 1
        px = life[j][4] * (1 - COSTS["half_spread"] - COSTS["slippage"])
    sell_fee = COSTS["maker"] if out == "TARGET" else COSTS["taker"]
    net = (px * (1 - sell_fee)) / (entry * (1 + COSTS["maker"])) - 1
    exit_t = datetime.fromtimestamp((life[j][5] + 1) / 1000, timezone.utc) if life else fill_t
    return dict(res, status=out, exit=round(px, 2), exit_time=iso(exit_t), net=round(net, 6))


# ------------------------------------------------------------------------------------------- record (chain)
def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_lines(repo: Path) -> list:
    p = repo / "trade_engine" / "trades.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def append(repo: Path, lines: list, kind: str, data: dict, now: datetime) -> dict:
    prev = lines[-1]["hash"] if lines else "0" * 64
    e = {"seq": len(lines) + 1, "kind": kind, "recorded_at": iso(now), "engine": ENGINE, "data": data, "prev": prev}
    e["hash"] = hashlib.sha256((prev + canon({k: v for k, v in e.items() if k != "hash"})).encode()).hexdigest()
    lines.append(e)
    p = repo / "trade_engine" / "trades.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fh.write(canon(e) + "\n")
    return e


def verify(repo: Path) -> list:
    errs, prev = [], "0" * 64
    for i, e in enumerate(load_lines(repo), 1):
        h = hashlib.sha256((prev + canon({k: v for k, v in e.items() if k != "hash"})).encode()).hexdigest()
        if e.get("seq") != i or e.get("prev") != prev or e.get("hash") != h:
            errs.append(f"line {i}: chain broken")
        prev = e.get("hash", "")
    return errs


def load_state(repo: Path) -> dict:
    p = repo / "trade_engine" / "state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def cmd_update(in_file: str, repo_dir: str = ".") -> int:
    repo = Path(repo_dir)
    inp = json.loads(Path(in_file).read_text())
    now = ts(inp["fetched_at"])
    lines = load_lines(repo)
    if verify(repo):
        print("te: chain broken, nothing written")
        return 1
    scanned = {l["data"]["t"] for l in lines if l["kind"] == "SCAN"}
    orders = {l["seq"]: l for l in lines if l["kind"] == "ORDER"}
    closed = {l["data"]["order"] for l in lines if l["kind"] == "RESULT"}
    filled = {l["data"]["order"] for l in lines if l["kind"] == "FILL"}
    # 1) resolve active orders first (a closed position frees the slot for this decision)
    for seq, l in orders.items():
        if seq in closed:
            continue
        r = simulate(l["data"], inp["m15"], ts(l["recorded_at"]), now)
        if r["status"] in ("OPEN", "TARGET", "STOP", "TIME") and seq not in filled:
            append(repo, lines, "FILL", {"order": seq, "fill_time": r["fill_time"], "entry": r["entry"]}, now)
            filled.add(seq)
        if r["status"] in ("NOT_FILLED", "NO_DATA", "TARGET", "STOP", "TIME"):
            append(repo, lines, "RESULT", dict(r, order=seq), now)
            closed.add(seq)
    # 2) the decision time whose recording window is open
    t = now.replace(minute=0, second=0, microsecond=0)
    t -= timedelta(hours=t.hour % 4)
    if now - t <= FRESH and t >= START and iso(t) not in scanned:
        fx = features(inp, t)
        busy = any(s not in closed for s in orders)
        sig = signal(fx)
        scan = {"t": iso(t), "signal": sig, "features": {k: (round(v, 8) if isinstance(v, float) else v) for k, v in fx.items()}}
        if sig and busy:
            scan["skipped"] = "a position or order is already active"
        append(repo, lines, "SCAN", scan, now)
        if sig and not busy:
            od = dict(order_from(fx, t), rule=RULE, costs=COSTS, data={"klines": KLINES, "funding": FUNDING})
            append(repo, lines, "ORDER", od, now)
    write_state(repo, lines, inp, now)
    print("te: lines", len(lines))
    return 0


def write_state(repo: Path, lines: list, inp: dict, now: datetime) -> None:
    orders = [l for l in lines if l["kind"] == "ORDER"]
    res = {l["data"]["order"]: l["data"] for l in lines if l["kind"] == "RESULT"}
    fills = {l["data"]["order"]: l["data"] for l in lines if l["kind"] == "FILL"}
    nets = [r["net"] for r in res.values() if "net" in r]
    active = []
    for l in orders:
        if l["seq"] not in res:
            active.append(dict(l["data"], seq=l["seq"], recorded_at=l["recorded_at"],
                               status="OPEN" if l["seq"] in fills else "PENDING", **({"entry": fills[l["seq"]]["entry"], "fill_time": fills[l["seq"]]["fill_time"]} if l["seq"] in fills else {})))
    last = None
    if res:
        k = max(res)
        o = next(l for l in orders if l["seq"] == k)
        last = dict(o["data"], seq=k, **res[k])
    scans = [l for l in lines if l["kind"] == "SCAN"]
    price = inp["m15"][-1][4] if inp.get("m15") else None
    st = {"engine": ENGINE, "rule": RULE, "asset": "BTC", "experimental": True, "updated_at": iso(now),
          "started_at": iso(START), "price": price, "last_scan": scans[-1]["data"]["t"] if scans else None,
          "scans": len(scans), "active": active, "last_closed": last,
          "record": {"orders": len(orders), "not_filled": sum(1 for r in res.values() if r["status"] == "NOT_FILLED"),
                     "closed": len(nets), "wins": sum(1 for x in nets if x > 0), "losses": sum(1 for x in nets if x <= 0),
                     "mean_net_pct": round(100 * sum(nets) / len(nets), 3) if nets else None,
                     "total_net_pct": round(100 * (math.prod(1 + x for x in nets) - 1), 3) if nets else None},
          "pass_rule": "experimental until >= 60 filled trades and >= 12 weeks with PF > 1.2 (lower bound > 1) and mean net > 0"}
    p = repo / "trade_engine" / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=1))


def main(argv: list) -> int:
    if len(argv) >= 2 and argv[1] == "fetch":
        return cmd_fetch(argv[2], argv[3] if len(argv) > 3 else ".")
    if len(argv) >= 2 and argv[1] == "update":
        return cmd_update(argv[2], argv[3] if len(argv) > 3 else ".")
    if len(argv) >= 2 and argv[1] == "verify":
        e = verify(Path(argv[2] if len(argv) > 2 else "."))
        print("\n".join(e) or "te chain ok")
        return 1 if e else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
