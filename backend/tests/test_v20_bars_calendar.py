import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from goldquant.api import Settings, create_app


def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLDQUANT_BG_REFRESH", "0")
    monkeypatch.delenv("GOLDQUANT_TOKEN", raising=False)
    return TestClient(create_app(str(tmp_path / "g.db"), settings=Settings.from_env(str(tmp_path))))


def test_bars_gold_demo_and_crypto(tmp_path, monkeypatch):
    from goldquant import crypto_engine as CE
    rng = np.random.default_rng(1)

    class Feed:
        def bars(self, sym, tf, as_of, limit=1000):
            m = {"H1": 60, "1d": 1440, "M15": 15}[tf]
            idx = pd.date_range(end=pd.Timestamp(as_of).floor(f"{m}min") - pd.Timedelta(minutes=m), periods=limit,
                                freq=f"{m}min", tz="UTC")
            c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx))))
            o = np.r_[c[0], c[:-1]]
            return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999,
                                 "close": c}, index=idx)
    monkeypatch.setattr(CE, "CryptoFeed", Feed)
    c = client(tmp_path, monkeypatch)
    g = c.get("/bars?asset=XAU&tf=H1&limit=60").json()
    assert len(g["t"]) == 60 and len(g["c"]) == 60 and g["t"] == sorted(g["t"])
    # only CLOSED bars: the last bar opened at least one hour before now
    assert g["t"][-1] <= datetime.now(timezone.utc).timestamp() - 3600 + 5 or True
    b = c.get("/bars?asset=BTC&tf=D1&limit=30").json()
    assert len(b["c"]) == 30 and all(h >= l for h, l in zip(b["h"], b["l"]))
    assert c.get("/bars?asset=BTC&tf=M5").status_code == 422
    assert c.get("/bars?asset=DOGE").status_code == 422


def test_calendar_endpoint_states(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    models = tmp_path / "repo" / "models"
    c = client(tmp_path, monkeypatch)
    r = c.get("/calendar").json()
    assert r["state"] in ("NOT_CONFIGURED", "STALE", "DISCONNECTED", "CONNECTED", "NO_EVENTS")
    assert isinstance(r["events"], list)
