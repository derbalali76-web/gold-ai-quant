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
