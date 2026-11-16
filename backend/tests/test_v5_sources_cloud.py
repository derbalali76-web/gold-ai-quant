import gzip
import io
import json
import lzma
import struct
import tarfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from goldquant import cloud, setups
from goldquant.engine import DecisionEngine, PathService, PathState
from goldquant.features_ext import cross_asset_features, time_features
from goldquant.precision import feature_upgrade as FU
from goldquant.providers import dukascopy as DK
from goldquant.providers.history import HistoryStore
from goldquant.providers.http import HttpClient, Response
from goldquant.schemas import Mode
from goldquant.sources import etf as ETF
from goldquant.store import Store


# ---------------- Dukascopy
def _bi5(rows, scale):
    raw = b"".join(struct.pack(">5If", s, int(o * scale), int(c * scale), int(l * scale), int(h * scale), v)
                   for s, o, c, l, h, v in rows)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


def test_dukascopy_parse_scale_and_order():
    rows = [(0, 2650.10, 2650.50, 2649.90, 2650.80, 12.0), (60, 2650.50, 2651.00, 2650.40, 2651.20, 8.0),
            (120, 2651.0, 2651.0, 2651.0, 2651.0, 0.0)]  # zero-volume filler must be dropped
    df = DK.parse_day(_bi5(rows, 1000), "XAUUSD", date(2026, 1, 5))
    assert len(df) == 2 and df.attrs["scale"] == 1000
    assert df["high"].iloc[0] == pytest.approx(2650.80) and df["low"].iloc[0] == pytest.approx(2649.90)
    assert df.index[1] == pd.Timestamp("2026-01-05 00:01", tz="UTC")
    fx = DK.parse_day(_bi5([(0, 1.1, 1.1002, 1.0999, 1.1003, 5.0)], 100000), "EURUSD", date(2026, 1, 5))
    assert fx["close"].iloc[0] == pytest.approx(1.1002)


def test_dukascopy_rejects_implausible_and_corrupt():
    with pytest.raises(ValueError):
        DK.parse_day(_bi5([(0, 5.0, 5.0, 5.0, 5.0, 1.0)], 1), "XAUUSD", date(2026, 1, 5))
    with pytest.raises(ValueError):
        DK.parse_day(lzma.compress(b"x" * 23, format=lzma.FORMAT_ALONE), "XAUUSD", date(2026, 1, 5))


def test_dukascopy_url_and_fetch_range():
    assert DK.day_url("XAUUSD", date(2026, 1, 5)).endswith("/XAUUSD/2026/00/05/BID_candles_min_1.bi5")
    payload = _bi5([(i * 60, 2000 + i, 2000 + i, 1999 + i, 2001 + i, 1.0) for i in range(30)], 1000)

    def t(url, params, timeout):
        return Response(200, "", url, 1.0, payload) if "/06/" not in url else Response(404, "", url, 1.0, b"")
    imp = DK.DukascopyImporter(HttpClient(transport=t, sleep=lambda s: None))
    m1 = imp.fetch_range("XAUUSD", date(2026, 1, 5), date(2026, 1, 7))  # Mon..Wed, Tue missing (404)
    assert len(m1) == 60 and m1.index.is_monotonic_increasing
    m15 = DK.to_timeframe(m1, 15)
    assert len(m15) == 4 and m15["high"].iloc[0] == pytest.approx(2015)


# ---------------- extended features
def test_time_features_dst_aware():
    winter = pd.DatetimeIndex([pd.Timestamp("2026-01-12 08:00", tz="UTC")])
    summer = pd.DatetimeIndex([pd.Timestamp("2026-07-13 07:00", tz="UTC")])
    assert time_features(winter)["min_since_london_open"].iloc[0] == 0.0
    assert time_features(summer)["min_since_london_open"].iloc[0] == 0.0  # 08:00 BST
    fix = pd.DatetimeIndex([pd.Timestamp("2026-01-12 15:00", tz="UTC")])
    assert time_features(fix)["near_london_pm_fix"].iloc[0] == 1.0


def test_cross_asset_features_no_lookahead(demo_bars):
    g = demo_bars["M15"].iloc[:3000]
    ag = g * 0.0125
    t = g.index + pd.Timedelta(minutes=15)
    full = cross_asset_features(t, g, {"XAGUSD": ag})
    cut = cross_asset_features(t[:2000], g.iloc[:2000], {"XAGUSD": ag.iloc[:2000]})
    a, b = full.iloc[1999].to_numpy(float), cut.iloc[1999].to_numpy(float)
    assert np.allclose(np.nan_to_num(a), np.nan_to_num(b))


def test_feature_upgrade_never_promotes_synthetic(demo_bars):
    r = FU.compare(demo_bars["M15"], demo_bars["H1"], demo_bars["H4"], dataset_label="SYNTHETIC")
    assert set(r["variants"]) == {"production", "plus_time"}
    assert not any(v["promotable"] for v in r["variants"].values())
    from goldquant import model as M
    assert "dow_sin" not in M.FEATURES  # production feature list restored


# ---------------- setups
def test_setup_detection_rules():
    idx = pd.date_range("2026-01-12 00:00", periods=48, freq="15min", tz="UTC")  # winter: London = UTC
    c = np.full(48, 2000.0)
    df = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c}, index=idx)
    df.loc[idx[32], ["close", "high"]] = [2005.0, 2005.5]  # bar 08:00-08:15 closes above Asia high (2001)
    df.loc[idx[34], ["close", "high"]] = [2006.0, 2006.5]  # a second breakout the same day is ignored
    det = setups.detect(df)
    assert det["LONDON_BREAKOUT"].iloc[32] == 1 and det["LONDON_BREAKOUT"].iloc[34] == 0
    assert det["LONDON_BREAKOUT"].sum() == 1


def test_setups_evaluate_reports_costs(demo_bars):
    r = setups.evaluate(demo_bars["M15"], demo_bars["H1"], demo_bars["H4"])
    assert set(r["setups"]) == set(setups.SETUPS)
    for v in r["setups"].values():
        if "development_raw" in v and v["development_raw"]["accepted"]:
            assert v["development_raw"]["win_rate_ci95"] is not None


# ---------------- GLD holdings
def _xlsx(rows):
    df = pd.DataFrame(rows, columns=["Date", "GLD Close", "Total Net Asset Value Tonnes in the Trust"])
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        pd.DataFrame([["SPDR Gold Trust archive"], [""]]).to_excel(w, index=False, header=False, startrow=0)
        df.to_excel(w, index=False, startrow=3)
    return bio.getvalue()


def test_gld_archive_parse_and_flows():
    days = pd.bdate_range("2025-06-02", periods=60)
    tonnes = 870 + np.r_[np.zeros(55), [3, 6, 9, 12, 15]]
    rows = [[d.strftime("%d-%b-%Y"), 300.0, f"{t:,.2f}"] for d, t in zip(days, tonnes)]
    obs = ETF.parse_archive(_xlsx(rows), datetime.now(timezone.utc))
    assert len(obs) == 60
    assert all(pd.Timestamp(o["published_at"]) > pd.Timestamp(o["observed_at"]) for o in obs)
    fl = ETF.flows_as_of(pd.DataFrame(obs))
    assert fl["change_5d"] == pytest.approx(15.0) and fl["change_5d_z"] > 1.5


# ---------------- cloud mode
def test_export_import_roundtrip(tmp_path, demo_bars):
    hs = HistoryStore()
    hs.upsert_bars("TwelveData", "XAU/USD", "M15", demo_bars["M15"].tail(3000), datetime.now(timezone.utc))
    hs.upsert_observations("FRED", "DFII10", [{"observed_at": "2026-01-05T00:00:00+00:00",
                                               "published_at": "2026-01-06T22:00:00+00:00",
                                               "fetched_at": "x", "value": 1.9}])
    n = cloud.export_bars(hs, tmp_path, "TwelveData", "XAU/USD", "M15")
    cloud.export_bars(hs, tmp_path, "TwelveData", "XAU/USD", "M15")  # idempotent merge
    cloud.export_observations(hs, tmp_path, "FRED", "DFII10")
    hs2 = HistoryStore()
    counts = cloud.import_tree(hs2, tmp_path)
    back = hs2.load_bars("TwelveData", "XAU/USD", "M15")
    assert n == 3000 and len(back) == 3000 and counts["obs:FRED:DFII10"] == 1
    np.testing.assert_allclose(back["close"].to_numpy(), demo_bars["M15"].tail(3000)["close"].to_numpy(), atol=1e-4)


def test_download_repo_blocks_path_traversal(tmp_path, monkeypatch):
    bio = io.BytesIO()
    with tarfile.open(fileobj=bio, mode="w:gz") as tar:
        for name, data in (("owner-repo-abc/market_data/x.txt", b"ok"), ("owner-repo-abc/models/../../evil.txt", b"x"),
                           ("owner-repo-abc/secrets/k.txt", b"no")):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    import httpx

    class R:
        content = bio.getvalue()

        def raise_for_status(self):
            pass
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    dest = tmp_path / "repo"
    cloud.download_repo("o/r", "t", dest)
    assert (dest / "market_data" / "x.txt").read_bytes() == b"ok"
    assert not (tmp_path / "evil.txt").exists() and not (dest / "secrets").exists()


def test_prebuilt_models_respect_point_in_time(demo):
    ps = PathService()
    real = ps.get(demo, demo.default_as_of(), {tf: demo.bars(tf, demo.default_as_of(), 20000).df for tf in ("M15", "H1", "H4")})
    ps2 = PathService()
    ps2.set_prebuilt(real)
    as_of = demo.default_as_of()
    assert ps2.get(demo, as_of, {}) is real  # served without training
    earlier = as_of - timedelta(hours=1)  # model trained AFTER this time must not be used
    with pytest.raises(Exception):
        ps2.get(demo, earlier, {})  # falls through to training, which needs bars (empty here)


def test_save_load_path_state(tmp_path, demo):
    st = PathState(None, False, "x", None)
    cloud.save_path_state(st, tmp_path, {"trained_until": "t"})
    back, meta = cloud.load_path_state(tmp_path)
    assert back.reason_ar == "x" and meta["trained_until"] == "t"


def test_cloud_job_train_and_server_sync(tmp_path, demo_bars, monkeypatch):
    import importlib
    import shutil
    import sys
    from fastapi.testclient import TestClient
    repo = tmp_path / "repo_src"
    hs = HistoryStore()
    for tf in ("M15", "H1", "H4"):
        hs.upsert_bars("TwelveData", "XAU/USD", tf, demo_bars[tf], datetime.now(timezone.utc))
        cloud.export_bars(hs, repo / "market_data", "TwelveData", "XAU/USD", tf)
    monkeypatch.setenv("GOLDQUANT_REPO_ROOT", str(repo))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    job = importlib.import_module("cloud_job")
    job = importlib.reload(job)
    job.train(job.load())
    assert (repo / "models" / "path_state.pkl").exists()
    meta = json.loads((repo / "models" / "manifest.json").read_text())
    assert meta["dataset"].startswith("LIVE HISTORY") and "qualified" in meta

    monkeypatch.setattr(cloud, "download_repo", lambda r, t, dest, **k: shutil.copytree(repo, dest, dirs_exist_ok=True))
    monkeypatch.setenv("GOLDQUANT_DATA_REPO", "me/repo")
    monkeypatch.setenv("GOLDQUANT_REPO_TOKEN", "t")
    from goldquant.api import Settings, create_app
    app = create_app(str(tmp_path / "d.db"), settings=Settings(tmp_path / "data", "", "", False, False))
    c = TestClient(app)
    import time
    for _ in range(100):
        h = c.get("/health").json()["cloud"]
        if h["last_sync_ok"] is not None:
            break
        time.sleep(0.2)
    assert h["enabled"] and h["last_sync_ok"], h
    assert h["model"]["trained_until"] == meta["trained_until"]


def test_cloud_settings_default_public_repo_on_render(monkeypatch):
    from goldquant import cloud
    monkeypatch.delenv("GOLDQUANT_DATA_REPO", raising=False)
    monkeypatch.delenv("GOLDQUANT_REPO_TOKEN", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    assert cloud.cloud_settings()["repo"] == ""
    monkeypatch.setenv("RENDER", "true")
    assert cloud.cloud_settings() == {"repo": cloud.DEFAULT_REPO, "token": ""}


def test_download_repo_falls_back_without_token(monkeypatch, tmp_path):
    import io, tarfile, httpx
    from goldquant import cloud
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"{}"
        ti = tarfile.TarInfo("owner-repo-abc/models/touch_models.json"); ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    calls = []

    def fake_get(url, **kw):
        calls.append("Authorization" in kw["headers"])
        req = httpx.Request("GET", url)
        return httpx.Response(401, request=req) if kw["headers"].get("Authorization") else httpx.Response(200, content=buf.getvalue(), request=req)
    monkeypatch.setattr(httpx, "get", fake_get)
    cloud.download_repo("owner/repo", "expired", tmp_path / "repo")
    assert calls == [True, False]
    assert (tmp_path / "repo" / "models" / "touch_models.json").exists()
