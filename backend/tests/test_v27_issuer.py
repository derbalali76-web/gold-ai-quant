"""The ledger's independent issuer (ledger/issue.py, standard library only) must give exactly what the server gives
(goldquant.price_range.live / goldquant.hilo.live) from the same closed bars and the same published parameters.
If they ever disagree, the public record would mix two different models — this test is the guard."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from goldquant import crypto_store as CS
from goldquant import hilo as HL
from goldquant import price_range as PR

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("issue", ROOT / "ledger" / "issue.py")
IS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(IS)
MD = ROOT / "market_data"


def _bars(df: pd.DataFrame):
    return [(t.to_pydatetime(), float(r.open), float(r.high), float(r.low), float(r.close)) for t, r in df.iterrows()]


def _rel(a, b):
    return abs(a - b) / max(abs(b), 1e-12)


def _synthetic(n=1100, seed=3):
    rng = np.random.default_rng(seed)
    c = 30000 * np.exp(np.cumsum(rng.standard_t(4, n) * 0.004))
    o = np.r_[c[0], c[:-1]]
    idx = pd.date_range("2026-09-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999, "close": c},
                        index=idx)


def _cases():
    out = []
    for name in ("range_models.json", "hilo_models.json"):
        p = ROOT / "models" / name
        if p.exists():
            for a, hs in json.loads(p.read_text(encoding="utf-8"))["assets"].items():
                for h, x in hs.items():
                    if a != "XAU" and x.get("params"):
                        out.append((name, a, h, x["params"]))
    return out


@pytest.mark.parametrize("name,asset,h,params", _cases())
def test_issuer_matches_server(name, asset, h, params):
    sym = IS.SYMBOLS[asset]
    real = CS.load_bars(MD, sym, "1h") if (MD / "crypto" / sym / "1h").exists() else None
    for df in ([real.tail(1000)] if real is not None and len(real) > 1000 else []) + [_synthetic()]:
        now = df.index[-1] + pd.Timedelta(hours=1)
        if name.startswith("range"):
            want = PR.live(params, df, now)
            got = IS.range_live(params, _bars(df))
            keys = ("low", "high", "close_at_issue")
        else:
            want = HL.live(params, df, now)
            got = IS.hilo_live(params, _bars(df))
            keys = tuple(f"{k}_{s}" for k in ("m", "b1", "b2") for s in ("lower", "upper")) + ("close_at_issue",)
        assert want is not None and got is not None
        assert pd.Timestamp(got["issued_at"]) == pd.Timestamp(want["issued_at"])
        for k in keys:
            assert _rel(got[k], want[k]) < 1e-9, (asset, h, k, got[k], want[k])
        assert got["version"] == want["version"] and got["bars"] == want["bars"]


def test_only_closed_bars_and_no_price():
    df = _synthetic()
    df.index = df.index - (df.index[-1] - pd.Timestamp("2026-11-16T20:00:00Z"))  # forming bar opens at 20:00
    rows = [[int(t.timestamp() * 1000), str(r.open), str(r.high), str(r.low), str(r.close)] for t, r in df.iterrows()]
    now = df.index[-1].to_pydatetime() + timedelta(minutes=30)  # the last bar is still forming
    bars = IS.closed_bars(rows, timedelta(hours=1), now)
    assert bars[-1][0] == df.index[-2].to_pydatetime()
    hp = json.loads((ROOT / "models" / "hilo_models.json").read_text(encoding="utf-8"))["assets"]
    snap = IS.issue("BTC", bars, [], {}, hp, now)
    assert snap["price"] is None and snap["source"] == "ledger-action"
    assert {r["horizon"] for r in snap["hilo"]} == {"4h", "24h"}
    for r in snap["hilo"]:
        assert r["issued_at"] == IS.iso(df.index[-1].to_pydatetime())  # decision at the close of the last CLOSED bar
        assert r["m_lower"] < r["close_at_issue"] < r["m_upper"]
    assert IS.issue("SOL", bars, [], {}, hp, now)["hilo"] == []  # not a pre-registered case


def test_issuer_snapshot_is_recorded_once_and_server_is_backup(tmp_path):
    spec2 = importlib.util.spec_from_file_location("ledger", ROOT / "ledger" / "ledger.py")
    L = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(L)
    df = _synthetic()
    df.index = df.index - (df.index[-1] - pd.Timestamp("2026-11-16T19:00:00Z"))  # last closed bar ends 20:00
    now = datetime(2026, 11, 16, 20, 5, tzinfo=timezone.utc)
    hp = json.loads((ROOT / "models" / "hilo_models.json").read_text(encoding="utf-8"))["assets"]
    snap = IS.issue("BTC", _bars(df), [], {}, hp, now)
    led = L.Ledger(tmp_path)
    led.ingest(snap, now)
    server = json.loads(json.dumps(snap))
    server.pop("source")
    for r in server["hilo"]:
        r["m_upper"] *= 1.01  # a server computed from stale parameters: never overwrites what is recorded
    led.ingest(server, now + timedelta(minutes=2))
    hl = [e for e in led.entries if e["kind"] == "HILO"]
    assert len(hl) == 2 and all(e["data"]["source"] == "ledger-action" for e in hl)
    assert not [e for e in led.entries if e["kind"] in ("REC", "BRIEF")]
    assert led.verify() == []


def test_a_missed_run_is_recorded_by_the_next_one_exactly_as_on_time():
    df = _synthetic()
    df.index = df.index - (df.index[-1] - pd.Timestamp("2026-11-16T20:00:00Z"))  # bars to 21:00 close
    hp = json.loads((ROOT / "models" / "hilo_models.json").read_text(encoding="utf-8"))["assets"]
    bars = _bars(df)
    on_time = IS.issue("BTC", bars[:-1], [], {}, hp, datetime(2026, 11, 16, 20, 1, tzinfo=timezone.utc))
    late_now = datetime(2026, 11, 16, 21, 4, tzinfo=timezone.utc)  # the 20:00 run failed; the 21:00 run catches up
    late = IS.issue("BTC", bars, [], {}, hp, late_now, {"hilo": "2026-11-15T04:00:00+00:00"})
    assert late["hilo"] == on_time["hilo"] and late["hilo"][0]["issued_at"] == "2026-11-16T20:00:00Z"
    # parameters exported after the issue time are never used for it
    assert IS.issue("BTC", bars, [], {}, hp, late_now, {"hilo": "2026-11-16T20:30:00+00:00"})["hilo"] == []
    assert IS.issue("BTC", bars, [], {}, hp, late_now, None)["hilo"] == []
    # past the 75-minute window: nothing
    assert IS.issue("BTC", bars, [], {}, hp, datetime(2026, 11, 16, 21, 16, tzinfo=timezone.utc),
                    {"hilo": "2026-11-15T04:00:00+00:00"})["hilo"] == []
    # an hour that is not an issue time computes nothing
    assert IS.due_slot(bars[:-3], datetime(2026, 11, 16, 18, 2, tzinfo=timezone.utc)) is None


# ---------------------------------------------------------------- gold (Twelve Data feed, since 2026-11-17)
from goldquant import cloud as CL  # noqa: E402
from goldquant.providers.base import closed_bars as server_closed  # noqa: E402


def _gold_h1():
    d = MD / "bars" / "TwelveData" / "XAUUSD" / "H1"
    files = sorted(d.glob("*.csv.gz")) if d.exists() else []
    if not files:
        return None
    df = pd.concat([CL.read_bars_file(f) for f in files]).sort_index()
    return df[~df.index.duplicated(keep="last")]


def _payload(df):
    return {"values": [{"datetime": t.strftime("%Y-%m-%d %H:%M:%S"), "open": f"{r.open}", "high": f"{r.high}",
                        "low": f"{r.low}", "close": f"{r.close}"} for t, r in df.iterrows()], "status": "ok"}


def test_gold_issuer_matches_server_on_twelve_data_bars():
    df = _gold_h1()
    if df is None or len(df) < 1100:
        pytest.skip("no stored Twelve Data gold history")
    params = json.loads((ROOT / "models" / "range_models.json").read_text(encoding="utf-8"))["assets"]["XAU"]
    # an issue time that traded: the latest bar whose close is on the 4-hour grid
    t_last = next(t for t in reversed(df.index) if (t + pd.Timedelta(hours=1)).hour % 4 == 0)
    now = t_last + pd.Timedelta(hours=1, minutes=3)
    srv = server_closed(df, "H1", now.to_pydatetime()).tail(1000)  # what the server's bars() returns
    got_bars = IS.twelve_bars(_payload(df[df.index <= t_last + pd.Timedelta(hours=2)]), now.to_pydatetime())
    assert [b[0] for b in got_bars[-1000:]] == [t.to_pydatetime() for t in srv.index]
    for h, x in params.items():
        want = PR.live(x["params"], srv, now)
        got = IS.range_live(x["params"], got_bars[-1000:])
        assert want is not None and got is not None
        assert pd.Timestamp(got["issued_at"]) == pd.Timestamp(want["issued_at"])
        for k in ("low", "high"):
            assert _rel(got[k], want[k]) < 1e-9, (h, k)


def test_gold_issue_only_when_the_hour_before_traded():
    idx = pd.date_range("2026-10-01", "2026-11-21", freq="h", tz="UTC")
    rng = np.random.default_rng(9)
    c = 4000 * np.exp(np.cumsum(rng.normal(0, 0.002, len(idx))))
    df = pd.DataFrame({"open": c, "high": c * 1.001, "low": c * 0.999, "close": c}, index=idx)
    params = json.loads((ROOT / "models" / "range_models.json").read_text(encoding="utf-8"))["assets"]
    fri = datetime(2026, 11, 20, 20, 2, tzinfo=timezone.utc)  # Friday 15:00 New York: open
    bars = IS.twelve_bars(_payload(df), fri)
    snap = IS.issue_gold(bars, params, fri, {"range": "2026-11-15T00:00:00+00:00"})
    assert {r["horizon"] for r in snap["ranges"]} == {"4h", "24h", "1w"} and snap["price"] is None
    assert snap["ranges"][0]["issued_at"] == "2026-11-20T20:00:00Z"
    sat = datetime(2026, 11, 21, 0, 5, tzinfo=timezone.utc)  # Friday 19:00 New York: closed, weekend prints dropped
    assert IS.issue_gold(IS.twelve_bars(_payload(df), sat), params, sat)["ranges"] == []
    assert not IS.gold_open(datetime(2026, 11, 20, 22, 30, tzinfo=timezone.utc))  # daily break
    assert IS.gold_open(datetime(2026, 11, 22, 23, 30, tzinfo=timezone.utc))  # Sunday evening reopen


def test_gold_key_never_in_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "SECRET123")

    def boom(req, timeout):
        raise OSError(f"failed {req.full_url} with SECRET123")
    monkeypatch.setattr(IS.urllib.request, "urlopen", boom)
    monkeypatch.setattr(IS, "recorded", lambda *a: False)
    now = datetime(2026, 11, 17, 8, 1, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError) as e:
        IS.gold(tmp_path, {}, {}, now)
    assert "SECRET123" not in str(e.value) and "apikey" not in IS.TWELVE
    monkeypatch.delenv("TWELVEDATA_API_KEY")
    assert "no TWELVEDATA_API_KEY" in IS.gold(tmp_path, {}, {}, now)


def test_gold_issue_recorded_once_server_compared(tmp_path):
    spec2 = importlib.util.spec_from_file_location("ledger_g", ROOT / "ledger" / "ledger.py")
    L = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(L)
    idx = pd.date_range("2026-10-01", "2026-11-17T07:00", freq="h", tz="UTC")
    c = 4000 * np.exp(np.cumsum(np.random.default_rng(2).normal(0, 0.002, len(idx))))
    df = pd.DataFrame({"open": c, "high": c * 1.001, "low": c * 0.999, "close": c}, index=idx)
    params = json.loads((ROOT / "models" / "range_models.json").read_text(encoding="utf-8"))["assets"]
    now = datetime(2026, 11, 17, 8, 2, tzinfo=timezone.utc)
    snap = IS.issue_gold(IS.twelve_bars(_payload(df), now), params, now)
    led = L.Ledger(tmp_path)
    led.ingest(snap, now)
    rg = [e for e in led.entries if e["kind"] == "RANGE"]
    assert [(e["data"]["asset"], e["data"]["horizon"], e["data"]["source"]) for e in rg] == [("XAU", "4h", "ledger-action")]
    server = dict(json.loads(json.dumps(snap)), source=None)
    led.ingest(server, now + timedelta(minutes=1))
    assert len([e for e in led.entries if e["kind"] == "RANGE"]) == 1 and led.checks[-1]["agree"]
    assert led.verify() == []
