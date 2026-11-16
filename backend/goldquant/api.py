"""FastAPI service.

Endpoints: /health /data-status /decision /history /model-metrics /engines /paper
           /research/backtest /research/micro-edge /research/info-value /research/granger
Research endpoints use stored LIVE history when enough exists, otherwise the labelled synthetic set.
Optional shared token: set GOLDQUANT_TOKEN and send header X-Goldquant-Token (all endpoints except /health).
"""
from __future__ import annotations

import logging

import dataclasses
import hmac
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query

from . import backtest as BT
from . import cloud
from . import engines_registry
from . import path as P
from .context import ContextService
from .engine import DecisionEngine, FETCH_BARS
from .intel import divergence as DIV
from .intel import info_value as IV
from .intel import micro_edge as ME
from .paper import PaperLedger
from .precision import report as PREC
from .precision.production import PrecisionService
from .reliability import adversarial as ADV
from .reliability import integrity as INT
from .reliability.execution import ExecutionModel
from .reliability.governance import ModelRegistry
from .reliability.shadow import ShadowBook
from .providers.base import utcnow
from .providers.demo import DemoProvider
from .providers.history import HistoryStore
from .providers.live import LiveProvider
from .providers.twelvedata import SYMBOL, TwelveDataProvider
from .providers.xaus import XausSpot
from .schemas import SCHEMA_VERSION, Action, Decision, Mode
from .msg import M as Mg
from .risk import EST_SLIPPAGE, EST_SPREAD
from .store import Store

APP_VERSION = "0.3.0"


@dataclasses.dataclass
class Settings:
    data_dir: Path
    td_key: str
    token: str
    xaus_check: bool
    context_enabled: bool

    @classmethod
    def from_env(cls, data_dir: Optional[str] = None) -> "Settings":
        return cls(Path(data_dir or os.environ.get("GOLDQUANT_DATA_DIR", "data")),
                   os.environ.get("TWELVEDATA_API_KEY", ""), os.environ.get("GOLDQUANT_TOKEN", ""),
                   os.environ.get("GOLDQUANT_XAUS_CHECK", "1") == "1",
                   os.environ.get("GOLDQUANT_CONTEXT", "1") == "1")


def create_app(db_path: Optional[str] = None, settings: Optional[Settings] = None,
               live_provider=None, context: Optional[ContextService] = None) -> FastAPI:
    st = settings or Settings.from_env()
    mem = db_path == ":memory:"
    store = Store(":memory:" if mem else (db_path or st.data_dir / "goldquant.db"))
    history = HistoryStore(":memory:" if mem else st.data_dir / "history.db")
    paper = PaperLedger(":memory:" if mem else st.data_dir / "paper.db")
    precision = None if mem else PrecisionService(st.data_dir)
    registry = ModelRegistry(st.data_dir / "model_registry.json") if not mem else None
    shadow = ShadowBook(":memory:" if mem else st.data_dir / "shadow.db")
    experiments = INT.ExperimentLedger(st.data_dir / "experiments.jsonl") if not mem else None
    engine = DecisionEngine(store, precision=precision, ledger=paper, registry=registry, shadow=shadow)
    demo = DemoProvider()
    if live_provider is None and st.td_key:
        live_provider = LiveProvider(TwelveDataProvider(st.td_key, history), XausSpot() if st.xaus_check else None)
    cs = cloud.cloud_settings()
    cloud_on = bool(cs["repo"]) and not mem  # the repository is public: the token is optional
    repo_dir = st.data_dir / "repo"
    if context is None and st.context_enabled and not mem:
        context = ContextService(history, (repo_dir / "config" / "calendar.json") if cloud_on else st.data_dir / "calendar.json",
                                 auto_calendar_path=(repo_dir / "models" / "calendar_auto.json") if cloud_on
                                 else st.data_dir / "calendar_auto.json")
    sync_state = {"last": 0.0, "ok": None, "error": None, "counts": {}, "model": None, "running": False}
    sync_done = threading.Event()

    def cloud_sync():
        """Pull market data + CI-trained models from the private repo (never trains on the request path)."""
        if sync_state["running"]:
            return
        sync_state["running"] = True
        try:
            cloud.download_repo(cs["repo"], cs["token"], repo_dir)
            sync_state["counts"] = cloud.import_tree(history, repo_dir / "market_data")
            stt, meta = cloud.load_path_state(repo_dir / "models")
            if stt is not None:
                engine.paths.set_prebuilt(stt)
                sync_state["model"] = meta
            import pickle as _pk
            engine.planners = {}
            for hz in ("WEEK", "MONTH"):
                pp = repo_dir / "models" / f"planner_{hz}.pkl"
                if pp.exists():
                    engine.planners[hz] = _pk.loads(pp.read_bytes())
            lvl_p = repo_dir / "models" / "levels_model.pkl"
            if lvl_p.exists():
                import pickle
                engine.level_service.set_prebuilt(pickle.loads(lvl_p.read_bytes()))
            for f in ("precision_report.json", "promotions.json"):
                if (repo_dir / "models" / f).exists():
                    shutil.copy(repo_dir / "models" / f, st.data_dir / f)
            sync_state.update(ok=True, error=None)
        except Exception as exc:  # noqa: BLE001 — reported in /health, decisions fall back to UNAVAILABLE/WAIT
            sync_state.update(ok=False, error=str(exc)[:300])
            logging.getLogger("goldquant.cloud").warning("repo sync failed: %s", str(exc)[:200])
        finally:
            sync_state["last"] = time.time()
            sync_state["running"] = False
            sync_done.set()

    if cloud_on:
        threading.Thread(target=cloud_sync, daemon=True).start()

    app = FastAPI(title="GOLD AI QUANT", version=APP_VERSION)
    app.state.engine, app.state.demo, app.state.paper = engine, demo, paper
    research_lock = threading.Lock()
    cache: dict = {}

    def auth(x_goldquant_token: str | None = Header(default=None)):
        if st.token and not (x_goldquant_token and hmac.compare_digest(x_goldquant_token, st.token)):
            raise HTTPException(401, "invalid or missing token")

    def demo_as_of(step: int) -> datetime:
        if step < 0 or step > 200:
            raise HTTPException(422, "demo_step must be in [0, 200]")
        idx = demo.m1().index
        target = idx[-1] - pd.Timedelta(hours=7 * step)
        pos = idx.searchsorted(target, side="right") - 1
        return (idx[max(pos, 0)] + pd.Timedelta(minutes=1)).to_pydatetime()

    def research_bars():
        dk = {tf: history.load_bars("Dukascopy", "XAUUSD", tf) for tf in ("M15", "H1", "H4")}
        if len(dk["M15"]) >= 4000 and len(dk["H4"]) >= 300:
            return dk, "LIVE HISTORY (Dukascopy)"
        if live_provider is not None or cloud_on:
            b = {tf: history.load_bars("TwelveData", SYMBOL, tf) for tf in ("M15", "H1", "H4")}
            if len(b["M15"]) >= 4000 and len(b["H4"]) >= 300:
                return b, "LIVE HISTORY (TwelveData)"
        as_of = demo.default_as_of()
        return ({tf: demo.bars(tf, as_of, FETCH_BARS[tf]).df for tf in ("M15", "H1", "H4")},
                "SYNTHETIC DEMO — اختبار للآلية فقط وليس دليلاً على أداء السوق")

    def cached(key, fn):
        with research_lock:
            if key not in cache:
                cache[key] = fn()
            return cache[key]

    @app.get("/health")
    def health():
        return {"status": "ok", "app_version": APP_VERSION, "schema_version": SCHEMA_VERSION,
                "model_version": P.PATH_VERSION, "server_time_utc": utcnow().isoformat(),
                "live_provider_configured": live_provider is not None, "auth_required": bool(st.token),
                "precision_layer": {"promoted": sorted(precision.promoted()) if precision else [],
                                    "calibration_passed": bool(precision and precision.calibration_ok())},
                "trade_execution": "disabled (signals and paper trading only)",
                "cloud": {"enabled": cloud_on, "last_sync_ok": sync_state["ok"], "error": sync_state["error"],
                          "model": sync_state["model"],
                          "last_sync_age_s": round(time.time() - sync_state["last"]) if sync_state["last"] else None,
                          "model_files": sorted(x.name for x in (repo_dir / "models").glob("*.json"))
                          if (repo_dir / "models").exists() else []}}

    @app.get("/data-status", dependencies=[Depends(auth)])
    def data_status():
        provs = [dataclasses.asdict(demo.meta)]
        if live_provider is not None:
            provs.append({**dataclasses.asdict(live_provider.primary.meta), "last_error": live_provider.primary.last_error,
                          "stored_bars": {tf: history.count_bars("TwelveData", SYMBOL, tf) for tf in ("M15", "H1", "H4")},
                          "last_cross_check": live_provider.last_cross_check})
        ver = st.data_dir / "verification.json"
        import json as _json
        auto = (repo_dir / "models" / "calendar_auto.json") if cloud_on else st.data_dir / "calendar_auto.json"
        cal_info = {"status": "لم يُولَّد بعد — يُنشأ عند أول تشغيل collect"}
        if auto.exists():
            try:
                o = _json.loads(auto.read_text(encoding="utf-8"))
                cal_info = {"updated_at": o.get("updated_at"), "sources": o.get("sources"),
                            "next_events": [e for e in o.get("events", []) if e["time_utc"] >= utcnow().isoformat()[:19]][:6]}
            except ValueError:
                cal_info = {"status": "ملف التقويم التلقائي تالف"}
        if context is not None:
            cs_ = context.calendar_status(utcnow())
            cs_.pop("cal", None)
            cal_info = {**cal_info, "state": cs_["state"], "last_successful_update": cs_["updated_at"],
                        "reason": cs_["reason"]}
        return {"providers": provs, "live_provider_configured": live_provider is not None,
                "economic_calendar": cal_info,
                "context_enabled": context is not None,
                "verification": ver.read_text(encoding="utf-8") if ver.exists() else "لم يُشغَّل فحص العقود الحي بعد",
                "recent_fetches": history.recent_fetches(30),
                "gaps": ["لا عمق سوق حقيقي متاح مجاناً", "لا إجماع توقعات اقتصادية مجاني مُتحقق منه",
                         "الحجم في الذهب الفوري غير مركزي — لا يُعامل كحجم حقيقي"]}

    live_cache: dict = {"d": None, "t": 0.0}
    live_lock = threading.Lock()
    LIVE_TTL = float(os.getenv("GOLDQUANT_LIVE_TTL_S", "300"))  # a decision is reused for a few minutes

    def compute_live() -> Decision:
        """The slow part (data fetch + models). Runs in the background loop and, if needed, on a request."""
        if cloud_on:
            sync_done.wait(timeout=60)  # first request after a cold start waits for the snapshot
            if time.time() - sync_state["last"] > 3600:
                threading.Thread(target=cloud_sync, daemon=True).start()
        now = utcnow()
        ctx = None
        if context is not None:
            context.refresh(now)
            ctx = context.snapshot(now)
        d = engine.decide(live_provider, Mode.LIVE, now, ctx)
        attach_scenario_history("XAU", d)
        if live_provider is not None:
            b = live_provider.bars("M15", now, 2000)
            if b is not None:
                paper.resolve(b.df, now, cost=EST_SPREAD + EST_SLIPPAGE)
                shadow.resolve(b.df, now)
            if registry is not None:
                st_ = paper.stats()
                registry.monitor(st_, None, bool(engine.paths._cache and any(
                    v.drift and v.drift.alarm for v in engine.paths._cache.values())))
        paper.record(d)
        return d

    def attach_live_track(d: Decision) -> Decision:
        """Fill each horizon's track record: live forward counts + performance blocks (never changes the decision)."""
        import json as _json
        from . import paper as PAPER
        from .schemas import PerfStats

        def jload(name):
            for base in (repo_dir / "models", st.data_dir):
                p = base / name
                if p.exists():
                    try:
                        return _json.loads(p.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        return None
            return None
        track = (jload("outlook_track.json") or {}).get("horizons", {})
        hours_ci = (jload("hours_track.json") or {}).get("HOURS")
        bt = jload("backtest_report.json") or {}
        plr = jload("planner_report.json") or {}
        local = PAPER.perf(PAPER.export_rows(paper)) if paper is not None else None
        for o in d.outlooks:
            perf = []
            if o.horizon == "HOURS":
                if bt.get("trades"):
                    perf.append(PerfStats(source="OOS_BACKTEST", unit="USD_OZ", trades=int(bt["trades"]),
                                          hits=int(round((bt.get("win_rate") or 0) * bt["trades"])),
                                          avg_win=bt.get("avg_win"), avg_loss=bt.get("avg_loss"),
                                          expectancy=bt.get("ev_per_trade"), max_drawdown=bt.get("max_drawdown"),
                                          period=f"{str(bt.get('start', ''))[:10]} → {str(bt.get('end', ''))[:10]}"))
                live = hours_ci if hours_ci and (hours_ci.get("trades") or hours_ci.get("pending")) else local
                if live:
                    perf.append(PerfStats(source="LIVE_FORWARD" if live is hours_ci else "LIVE_PAPER", unit="USD_OZ",
                                          **{k: live.get(k) for k in ("trades", "hits", "pending", "not_filled", "avg_win",
                                                                      "avg_loss", "expectancy", "max_drawdown", "period")}))
                    o.live_resolved, o.live_hits = int(live.get("trades") or 0), int(live.get("hits") or 0)
            if o.horizon in plr and plr[o.horizon].get("trades") is not None:
                r = plr[o.horizon]
                perf.append(PerfStats(source="OOS_PLANNER", unit="PCT", trades=int(r.get("trades") or 0),
                                      hits=int(round((r.get("tp_first_rate") or 0) * (r.get("trades") or 0))),
                                      not_filled=int(r.get("not_filled") or 0), avg_win=r.get("avg_win_pct"),
                                      avg_loss=r.get("avg_loss_pct"), expectancy=r.get("expectancy_pct"),
                                      max_drawdown=r.get("max_drawdown_pct"), period=r.get("period"),
                                      direction_accuracy=r.get("direction_accuracy"),
                                      direction_baseline=r.get("direction_baseline"),
                                      baseline_expectancy=r.get("baseline_expectancy_pct"),
                                      qualified=bool(r.get("qualified")), verdict=r.get("reason")))
            if o.horizon != "HOURS" and o.horizon in track:
                t = track[o.horizon]
                o.live_resolved = int(t.get("resolved") or 0)
                o.live_hits = int(t.get("hits") or 0)
                perf.append(PerfStats(source="LIVE_FORWARD", unit="PCT", trades=o.live_resolved, hits=o.live_hits,
                                      pending=int(t.get("pending") or 0), avg_win=t.get("avg_win_pct"),
                                      avg_loss=t.get("avg_loss_pct"), expectancy=t.get("expectancy_pct"),
                                      max_drawdown=t.get("max_drawdown_pct")))
            o.performance = perf
        return d

    guard: dict = {}  # asset -> {"t": last fetch, "off": {horizon: completed trades}} (models losing in the LIVE record)
    LEDGER_STATS = os.getenv("GOLDQUANT_LEDGER_STATS",
                             "https://raw.githubusercontent.com/derbalali76-web/ai-quant-ledger/main/stats.json")

    def live_guard(d: Decision, asset: str = "XAU") -> Decision:
        """Automatic switch-off: a horizon whose recommendations are losing in the public ledger (>= 20 completed and
        average R < 0, or >= 40 and worse than the always-buy baseline) issues no recommendation until revalidated."""
        g = guard.setdefault(asset, {"t": 0.0, "off": {}})  # per asset: one coin's record never switches another
        if time.time() - g["t"] > 3600:
            g["t"] = time.time()
            try:
                import json as _json
                from .providers.http import HttpClient
                st_ = _json.loads(HttpClient(retries=1, timeout=10.0).get(LEDGER_STATS).text)
                node = st_ if asset == "XAU" else (st_.get("assets") or {}).get(asset, {})
                off = {}
                for hz, b in (node.get("by_horizon") or {}).items():
                    n, r, base = b.get("completed") or 0, b.get("avg_r"), b.get("baseline_avg_r")
                    if r is not None and ((n >= 20 and r < 0) or (n >= 40 and base is not None and r < base)):
                        off[hz] = n
                g["off"] = off
            except Exception:  # noqa: BLE001 — unreachable ledger: keep the last known state
                pass
        from .engine import _ref
        from .schemas import Setup, TradePlan
        for o in d.outlooks:
            n = g["off"].get(o.horizon)
            if n is None:
                continue
            msg = Mg("va.live_disabled", n)
            if o.plan is not None and o.plan.recommendation:
                o.plan = TradePlan(setup=Setup.WAIT, method=o.plan.method)
            o.validated, o.validation_ar, o.validation_ref = False, str(msg), _ref(msg)
            if o.horizon == "HOURS" and d.action in (Action.BUY, Action.SELL):
                d.action = Action.WAIT
        return d

    def refresh_live(force: bool = False) -> Decision:
        with live_lock:  # one computation at a time; concurrent callers reuse its result
            if not force and live_cache["d"] is not None and time.time() - live_cache["t"] < LIVE_TTL:
                return live_cache["d"]
            d = live_guard(attach_live_track(compute_live()))
            live_cache.update(d=d, t=time.time())
            return d

    from .push import PushService
    push = PushService(st.data_dir)

    def push_decision(a: str):
        if a == "XAU":
            return refresh_live() if live_provider is not None else None
        return crypto_decision(a)

    def live_loop():
        time.sleep(20)
        while True:
            try:
                refresh_live(force=time.time() - live_cache["t"] >= LIVE_TTL)
            except Exception:  # noqa: BLE001 — the next request/loop pass reports the real state
                pass
            try:  # while the server is awake, phones get their alerts from here
                push.tick(push_decision)
            except Exception as exc:  # noqa: BLE001
                logging.getLogger("goldquant.push").warning("push tick failed: %s", type(exc).__name__)
            time.sleep(max(30.0, LIVE_TTL / 2))

    if live_provider is not None and not mem and os.getenv("GOLDQUANT_BG_REFRESH", "1") == "1":
        threading.Thread(target=live_loop, daemon=True).start()

    crypto_state: dict = {"feed": None, "levels": None, "cache": {}}

    ctx_cache: dict = {"t": 0.0, "ctx": None}

    def shared_context():
        """Calendar & macro context for the crypto engines (snapshot only; refreshing stays in the gold loop)."""
        if context is None:
            return None
        if time.time() - ctx_cache["t"] > 60:
            try:
                ctx_cache["ctx"], ctx_cache["t"] = context.snapshot(utcnow()), time.time()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger("goldquant.calendar").warning("context snapshot failed: %s", type(exc).__name__)
                ctx_cache["ctx"], ctx_cache["t"] = None, time.time()
        return ctx_cache["ctx"]

    activity_state: dict = {"mtime": None, "params": {}}

    def attach_activity(asset: str, d: Decision) -> None:
        """Market-activity forecast for scalpers: only for coins that passed this week's validation."""
        from . import activity as ACT
        from .schemas import ScalpActivity
        p = None
        for base in (repo_dir / "models", st.data_dir):
            if (base / "activity_models.json").exists():
                p = base / "activity_models.json"
                break
        if p is None or d.action == Action.UNAVAILABLE:
            return
        try:
            mt = p.stat().st_mtime
            if activity_state["mtime"] != mt:
                import json as _json
                raw = _json.loads(p.read_text(encoding="utf-8"))
                activity_state["params"] = {}
                for a, v in raw.get("assets", {}).items():
                    prm_ = v.get("model")
                    if prm_ and prm_.get("calibrated_bins") is None:  # files exported before the display rule
                        prm_["calibrated_bins"] = ACT.calibrated_bins(v.get("report") or {})
                    activity_state["params"][a] = prm_
                activity_state["mtime"] = mt
            prm = activity_state["params"].get(asset)
            if not prm or not prm.get("qualified"):
                return
            try:  # the model is retrained weekly: show how recent its data is
                from . import source_status as SS
                end = str(prm.get("period") or "").split("->")[-1].strip()
                if end:
                    d.sources.append(SS.build(d.analyzed_at_utc, model_updated_at=pd.Timestamp(end, tz="UTC")
                                              + pd.Timedelta(days=1))[-1])
            except Exception:  # noqa: BLE001 — informative only
                pass
            m15 = crypto_state["feed"].bars(CE_SYMBOL(asset), "M15", utcnow())
            r = ACT.predict(prm, m15)
            if r is None:
                return
            level = "HIGH" if r["probability"] >= r["usual"] + 0.10 else "LOW" if r["probability"] <= r["usual"] - 0.10 \
                else "NORMAL"
            d.scalp_activity = ScalpActivity(probability=r["probability"], usual=r["usual"], level=level,
                                             target_pct=prm["target_pct"], hours=prm["hours"], skill=prm.get("skill"),
                                             holdout_skill=prm.get("holdout_skill"), validated_period=prm.get("period"),
                                             model_fitted_until=prm.get("fitted_until"))
        except Exception:  # noqa: BLE001 — an optional extra must never break the decision
            return

    def CE_SYMBOL(asset: str) -> str:  # noqa: N802
        from .crypto_engine import ASSETS
        return ASSETS[asset]

    hist_state: dict = {"mtime": None, "table": {}}

    def attach_scenario_history(asset: str, d: Decision) -> None:
        from . import brief as BR
        p = None
        for base in (repo_dir / "models", st.data_dir):
            if (base / "scenario_history.json").exists():
                p = base / "scenario_history.json"
                break
        if p is None or d.daily_brief is None or d.levels is None:
            return
        try:
            mt = p.stat().st_mtime
            if hist_state["mtime"] != mt:
                import json as _json
                hist_state["table"] = _json.loads(p.read_text(encoding="utf-8")).get("assets", {})
                hist_state["mtime"] = mt
            BR.attach_history(d.daily_brief, hist_state["table"].get(asset), d.levels.atr_h1)
            sc = {x.kind: x.trigger for x in d.daily_brief.scenarios}
            BR.attach_first_touch(d.daily_brief, hist_state["table"].get(asset), float(d.quote or 0),
                                  sc.get("BEAR"), sc.get("BULL"), d.levels.atr_h1)
        except Exception:  # noqa: BLE001 — descriptive extra
            return

    def crypto_decision(asset: str) -> Decision:
        from . import crypto_engine as CE
        from .levels import LevelService
        if crypto_state["feed"] is None:
            crypto_state["feed"], crypto_state["levels"] = CE.CryptoFeed(), LevelService()
        hit = crypto_state["cache"].get(asset)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        d = CE.decide(asset, crypto_state["feed"], utcnow(), crypto_state["levels"], shared_context())
        attach_activity(asset, d)
        attach_scenario_history(asset, d)
        crypto_state["cache"][asset] = (time.time(), d)
        return d

    @app.get("/decision", response_model=Decision, dependencies=[Depends(auth)])
    def decision(mode: Mode = Query(Mode.DEMO), demo_step: int = Query(0), asset: str = Query("XAU")):
        a = asset.upper()
        if a != "XAU":
            from .crypto_engine import ASSETS
            if a not in ASSETS:
                raise HTTPException(422, "asset must be XAU, BTC, ETH or SOL")
            return crypto_decision(a)
        if mode == Mode.DEMO:
            d = engine.decide(demo, Mode.DEMO, demo_as_of(demo_step))
            paper.record(d)
            return d
        return refresh_live()

    def public_snapshot(d: Decision, with_bars: bool = True) -> dict:
        """What the public trust ledger records: only published recommendations, today's analysis and closed bars.
        No token needed: it contains nothing that is not shown in the app, and it is what makes the record checkable."""
        recs = []
        for o in d.outlooks:
            p = o.plan
            if p is None or not p.recommendation or p.side not in ("BUY", "SELL") or p.stop_loss is None \
                    or p.target is None:
                continue
            recs.append({"horizon": o.horizon, "side": p.side, "order": p.order or "MARKET",
                         "entry_low": p.entry_low, "entry_high": p.entry_high, "stop": p.stop_loss,
                         "target": p.target, "method": p.method, "model_version": d.model_version,
                         "valid_until": p.valid_until_utc.isoformat() if p.valid_until_utc else None})
        bars = {}
        if live_provider is not None and with_bars:
            for tf, n in (("H1", 120), ("D1", 45)):
                try:
                    b = live_provider.bars(tf, d.analyzed_at_utc, n)
                except Exception:  # noqa: BLE001
                    b = None
                bars[tf] = [] if b is None else [[t.isoformat(), round(float(r.open), 3), round(float(r.high), 3),
                                                  round(float(r.low), 3), round(float(r.close), 3)]
                                                 for t, r in b.df.iterrows()]
        return {"schema": 1, "as_of": d.analyzed_at_utc.isoformat(), "symbol": "XAUUSD", "price": d.quote,
                "cost": EST_SPREAD + EST_SLIPPAGE, "market_closed": d.market_closed, "mode": d.mode.value,
                "model_version": d.model_version, "recommendations": recs if d.mode == Mode.LIVE else [],
                "brief": d.daily_brief.model_dump(mode="json") if d.daily_brief else None, "bars": bars,
                # for the public monitor: is the analysis healthy right now?
                "health": d.data_health.status if d.data_health else None, "action": d.action.value,
                "quote_time": d.quote_timestamp_utc.isoformat() if d.quote_timestamp_utc else None,
                "app_crashes_7d": crashes_recent()}

    crash_log = st.data_dir / "crashes.jsonl"

    def crashes_recent(days: int = 7) -> int:
        import json as _json
        if not crash_log.exists():
            return 0
        cut = (utcnow() - pd.Timedelta(days=days)).isoformat()
        return sum(1 for ln in crash_log.read_text(encoding="utf-8").splitlines()
                   if ln.strip() and _json.loads(ln).get("at", "") >= cut)

    bars_cache: dict = {}

    @app.get("/bars", dependencies=[Depends(auth)])
    def bars_endpoint(asset: str = Query("XAU"), tf: str = Query("H1"), limit: int = Query(120, ge=20, le=300)):
        """Closed candles for the in-app chart (no look-ahead: only complete bars). Cached 60 s."""
        a, tf = asset.upper(), tf.upper()
        if tf not in ("H1", "D1"):
            raise HTTPException(422, "tf must be H1 or D1")
        key = (a, tf, limit)
        hit = bars_cache.get(key)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        now = utcnow()
        if a == "XAU":
            prov = live_provider if live_provider is not None else demo
            b = prov.bars(tf, now, limit + 5)
            df = b.df if b is not None else None
        else:
            from . import crypto_engine as CE
            from .levels import LevelService
            if a not in CE.ASSETS:
                raise HTTPException(422, "asset must be XAU, BTC, ETH or SOL")
            if crypto_state["feed"] is None:
                crypto_state["feed"], crypto_state["levels"] = CE.CryptoFeed(), LevelService()
            ASSETS = CE.ASSETS
            df = crypto_state["feed"].bars(ASSETS[a], "H1" if tf == "H1" else "1d", now, limit + 5)
        if df is None or not len(df):
            raise HTTPException(503, "bars unavailable")
        df = df.tail(limit)
        out = {"asset": a, "tf": tf, "t": [int(x.timestamp()) for x in df.index],
               "o": [round(float(v), 6) for v in df["open"]], "h": [round(float(v), 6) for v in df["high"]],
               "l": [round(float(v), 6) for v in df["low"]], "c": [round(float(v), 6) for v in df["close"]]}
        bars_cache[key] = (time.time(), out)
        return out

    touch_state = {"mtime": None, "data": {}}

    @app.get("/touch", dependencies=[Depends(auth)])
    def touch_endpoint(asset: str = Query("XAU"), prices: str = Query(..., max_length=200)):
        """P(the price touches each level within 4 h / 24 h / 1 week), only for asset-horizons that passed the
        pre-registered weekly validation (goldquant/touch.py). Not a direction; never a recommendation."""
        from . import touch as TO
        a = asset.upper()
        try:
            want = [float(x) for x in prices.split(",") if x.strip()][:8]
        except ValueError:
            raise HTTPException(422, "prices must be numbers")
        if not want or any(not (x > 0) for x in want):
            raise HTTPException(422, "prices must be positive")
        p = next((b / "touch_models.json" for b in (repo_dir / "models", st.data_dir)
                  if (b / "touch_models.json").exists()), None)
        if p is None:  # the hourly sync has not brought the file yet: ask for one now (once per 5 min)
            if cloud_on and not sync_state["running"] and time.time() - (sync_state["last"] or 0) > 300:
                threading.Thread(target=cloud_sync, daemon=True).start()
            return {"asset": a, "available": False, "reason": "NO_MODEL_FILE", "horizons": {}}
        mt = p.stat().st_mtime
        if touch_state["mtime"] != mt:
            import json as _json
            touch_state["data"] = _json.loads(p.read_text(encoding="utf-8")).get("assets", {})
            touch_state["mtime"] = mt
        models = touch_state["data"].get(a) or {}
        now = utcnow()
        if a == "XAU":
            prov = live_provider if live_provider is not None else demo
            b = prov.bars("H1", now, 1000)
            h1 = b.df if b is not None else None
            lq = live_cache["d"].quote if live_provider is not None and live_cache["d"] is not None else None
            q = lq if lq else (float(h1["close"].iloc[-1]) if h1 is not None and len(h1) else None)
        else:
            from . import crypto_engine as CE
            from .levels import LevelService
            if a not in CE.ASSETS:
                raise HTTPException(422, "asset must be XAU, BTC, ETH or SOL")
            if crypto_state["feed"] is None:
                crypto_state["feed"], crypto_state["levels"] = CE.CryptoFeed(), LevelService()
            h1 = crypto_state["feed"].bars(CE.ASSETS[a], "H1", now, 1000)
            q = float(h1["close"].iloc[-1]) if h1 is not None and len(h1) else None
        out = {}
        for h, x in models.items():
            rep, prm = x.get("report") or {}, x.get("model")
            if not rep.get("qualified") or not prm:
                continue
            res = [r for r in (TO.live(prm, h1, v, float(q or 0)) for v in want) if r is not None]
            out[h] = {"results": res, "weak": bool((rep.get("holdout_skill") or 0) < 0.005),
                      "skill": rep.get("skill"), "holdout_skill": rep.get("holdout_skill")}
        return {"asset": a, "available": bool(out), "price": None if q is None else round(float(q), 6),
                "reason": None if out else ("NO_PRICE_DATA" if q is None else "NOT_VALIDATED"), "horizons": out}

    range_state = {"mtime": None, "data": {}}

    @app.get("/range", dependencies=[Depends(auth)])
    def range_endpoint(asset: str = Query("XAU")):
        """80 % interval for the CLOSE 4 h / 1 day ahead (goldquant/price_range.py, pre-registered). Only horizons that
        passed are returned; a 4 h interval with a high-impact event inside its window is withheld. Experimental:
        never a direction, a target or a recommendation."""
        from . import price_range as PRG
        a = asset.upper()
        if a not in ("XAU", "BTC", "ETH", "SOL"):
            raise HTTPException(422, "asset must be XAU, BTC, ETH or SOL")
        p = next((b / "range_models.json" for b in (repo_dir / "models", st.data_dir)
                  if (b / "range_models.json").exists()), None)
        if p is None:
            if cloud_on and not sync_state["running"] and time.time() - (sync_state["last"] or 0) > 300:
                threading.Thread(target=cloud_sync, daemon=True).start()
            return {"asset": a, "available": False, "reason": "NO_MODEL_FILE", "display": None, "horizons": {}}
        mt = p.stat().st_mtime
        if range_state["mtime"] != mt:
            import json as _json
            range_state["data"] = _json.loads(p.read_text(encoding="utf-8")).get("assets", {})
            range_state["mtime"] = mt
        models = range_state["data"].get(a) or {}
        now = utcnow()
        if a == "XAU":
            prov = live_provider if live_provider is not None else demo
            b = prov.bars("H1", now, 1000)
            h1 = b.df if b is not None else None
        else:
            from . import crypto_engine as CE
            from .levels import LevelService
            if crypto_state["feed"] is None:
                crypto_state["feed"], crypto_state["levels"] = CE.CryptoFeed(), LevelService()
            h1 = crypto_state["feed"].bars(CE.ASSETS[a], "H1", now, 1000)
        events = []
        if context is not None:
            cal = context.calendar_status(now).get("cal")
            if cal is not None:
                events = [e for e in cal.events if (e.importance or 0) >= 3]
        out = {}
        for h in ("4h", "24h"):
            x = models.get(h) or {}
            if not x.get("qualified") or not x.get("params"):
                continue
            r = PRG.live(x["params"], h1, pd.Timestamp(now))
            if r is None:
                continue
            ev = None
            if h == "4h":
                t0 = pd.Timestamp(r["issued_at"])
                hit = [e for e in events if t0 < pd.Timestamp(e.time_utc) <= t0 + pd.Timedelta(hours=4)]
                if hit:
                    ev = {"name": hit[0].name, "time_utc": hit[0].time_utc.isoformat()}
            out[h] = dict(r, event=ev, holdout_coverage=x.get("holdout_coverage"))
        disp = PRG.display_horizon({h: h in out for h in ("4h", "24h")})
        return {"asset": a, "available": bool(out), "experimental": True, "display": disp,
                "reason": None if out else ("NO_PRICE_DATA" if h1 is None or not len(h1) else "NOT_VALIDATED"),
                "horizons": out}

    @app.get("/calendar", dependencies=[Depends(auth)])
    def calendar_endpoint():
        """Economic calendar for the in-app screen: state, last successful update, events -12 h .. +7 days."""
        now = utcnow()
        if context is None:
            return {"state": "NOT_CONFIGURED", "updated_at": None, "events": []}
        cs_ = context.calendar_status(now)
        cal = cs_.pop("cal", None)
        evs = []
        if cal is not None:
            for e in sorted(cal.events, key=lambda e: e.time_utc):
                dt = (e.time_utc - now).total_seconds()
                if -12 * 3600 <= dt <= 7 * 86400:
                    evs.append({"time_utc": e.time_utc.isoformat(), "name": e.name, "importance": e.importance,
                                "source": e.source})
        return {"state": cs_["state"], "updated_at": cs_["updated_at"], "events": evs[:40]}

    @app.post("/push/register", dependencies=[Depends(auth)])
    def push_register(body: dict = Body(...)):
        """Phone registers its anonymous FCM token, followed assets and one-tap alerts (no personal data)."""
        try:
            return push.register(str(body.get("token", "")), list(body.get("assets") or []),
                                 list(body.get("alerts") or []), str(body.get("lang", "ar")))
        except ValueError:
            raise HTTPException(422, "bad token")

    @app.post("/push/unregister", dependencies=[Depends(auth)])
    def push_unregister(body: dict = Body(...)):
        push.unregister(str(body.get("token", "")))
        return {"ok": True}

    @app.post("/push/tick")
    @app.get("/push/tick")
    def push_tick():
        """Public on purpose (wake-up ping from GitHub Actions): throttled, idempotent, returns counts only."""
        return push.tick(push_decision)

    @app.get("/push/status", dependencies=[Depends(auth)])
    def push_status():
        return push.status()

    @app.post("/crash", dependencies=[Depends(auth)])
    def crash_report(payload: dict):
        """App crash reports (stack trace, app / Android version). Counted in the public snapshot so the public
        monitor raises an alert automatically; contents stay behind the token (GET /crashes)."""
        import json as _json
        rec = {"at": utcnow().isoformat(), "trace": str(payload.get("trace", ""))[:6000],
               "app": str(payload.get("app", ""))[:40], "android": str(payload.get("android", ""))[:10]}
        lines = crash_log.read_text(encoding="utf-8").splitlines()[-199:] if crash_log.exists() else []
        crash_log.write_text("\n".join(lines + [_json.dumps(rec, ensure_ascii=False)]) + "\n", encoding="utf-8")
        return {"ok": True}

    @app.get("/crashes", dependencies=[Depends(auth)])
    def crash_list():
        import json as _json
        if not crash_log.exists():
            return []
        return [_json.loads(ln) for ln in crash_log.read_text(encoding="utf-8").splitlines() if ln.strip()][-50:]

    @app.get("/data-quality", dependencies=[Depends(auth)])
    def data_quality_ep():
        """Full-history and last-7-days quality of every stored series (written daily by the CI train job)."""
        import json as _json
        for base in (repo_dir / "models", st.data_dir):
            p = base / "data_quality.json"
            if p.exists():
                return _json.loads(p.read_text(encoding="utf-8"))
        return {"series": {}, "note": "no report yet"}

    @app.get("/public/snapshot")
    def public_snapshot_ep(asset: str = Query("XAU")):
        a = asset.upper()
        if a != "XAU":
            from . import crypto_engine as CE
            from .levels import LevelService
            if a not in CE.ASSETS:
                raise HTTPException(422, "asset must be XAU, BTC, ETH or SOL")
            d = crypto_decision(a)
            feed = crypto_state["feed"]
            snap = public_snapshot(d, with_bars=False)
            bars = {}
            for tf, n in (("H1", 120), ("1d", 45)):
                try:
                    b = feed.bars(CE.ASSETS[a], tf, d.analyzed_at_utc).tail(n)
                except Exception:  # noqa: BLE001
                    b = None
                bars["D1" if tf == "1d" else tf] = [] if b is None else [
                    [t.isoformat(), round(float(r.open), 4), round(float(r.high), 4), round(float(r.low), 4),
                     round(float(r.close), 4)] for t, r in b.iterrows()]
            from .planner import ASSET_COST
            snap.update(asset=a, symbol=CE.ASSETS[a], bars=bars,
                        cost=round(float(d.quote or 0) * ASSET_COST.get(CE.ASSETS[a], 0.0022), 4))
            return snap
        if live_provider is None:
            raise HTTPException(503, "no live data source")
        return dict(public_snapshot(refresh_live()), asset="XAU")

    @app.get("/history", dependencies=[Depends(auth)])
    def history_ep(limit: int = Query(50, ge=1, le=500)):
        return {"decisions": store.history(limit)}

    @app.get("/audit/verify", dependencies=[Depends(auth)])
    def audit_verify():
        return store.verify_audit()

    @app.get("/audit/{decision_id}", dependencies=[Depends(auth)])
    def audit_get(decision_id: str):
        r = store.audit_record(decision_id)
        if r is None:
            raise HTTPException(404, "unknown decision_id")
        return r

    @app.get("/shadow", dependencies=[Depends(auth)])
    def shadow_ep():
        return shadow.leaderboard()

    @app.get("/governance", dependencies=[Depends(auth)])
    def governance_ep():
        return registry.state if registry else {"active": None, "versions": [], "events": [],
                                                "note": "in-memory instance"}

    @app.get("/research/adversarial", dependencies=[Depends(auth)])
    def research_adversarial():
        eng = DecisionEngine(Store())  # isolated: scenario decisions never enter the production audit trail
        as_of = (pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=3)).to_pydatetime()
        res = ADV.run_all(eng, demo, Mode.DEMO, as_of)
        return {"scenarios": res, "all_safe": all(r["safe"] for r in res)}

    @app.get("/research/integrity", dependencies=[Depends(auth)])
    def research_integrity():
        e = experiments.entries() if experiments else []
        return {"experiments_logged": len(e), "distinct_trials": experiments.trials() if experiments else 0,
                "recent": e[-20:]}

    @app.get("/paper", dependencies=[Depends(auth)])
    def paper_ep():
        return {"stats": paper.stats(), "open": paper.open_trades()[:50],
                "note_ar": "تداول ورقي فقط. لا تُعتبر النتائج موثوقة قبل 300 صفقة مغلقة على الأقل."}

    @app.get("/engines", dependencies=[Depends(auth)])
    def engines():
        return {"engines": engines_registry.as_dicts()}

    @app.get("/model-metrics", dependencies=[Depends(auth)])
    def model_metrics():
        def build():
            bars, label = research_bars()
            ds = P.build_path_dataset(bars["M15"], bars["H1"], bars["H4"])
            reps = {h: dataclasses.asdict(P.walk_forward_horizon(ds, h)) for h in P.HORIZONS_MIN}
            return {"dataset": label, "model_version": P.PATH_VERSION,
                    "label": "نتيجة من ثلاث: الهدف (1R) أولاً / الوقف (2×ATR M15) أولاً / لا شيء خلال الأفق؛ لمس الاثنين في نفس الشمعة = وقف",
                    "validation": "purged walk-forward + embargo بطول الأفق؛ آخر 20% محجوزة ولم تُلمس",
                    "samples": int(len(ds)), "horizons": reps,
                    "qualified_horizons": [h for h, r in reps.items() if r["qualified"]]}
        return cached("metrics", build)

    @app.get("/research/backtest", dependencies=[Depends(auth)])
    def research_backtest():
        def build():
            bars, label = research_bars()
            r = BT.run(bars["M15"], bars["H1"], bars["H4"], final=False)
            real = BT.run(bars["M15"], bars["H1"], bars["H4"], final=False, execution=ExecutionModel())
            r["dataset"] = label
            r["realistic_execution"] = {k: real[k] for k in ("trades", "win_rate", "win_rate_ci95", "ev_per_trade",
                                                               "ev_ci95", "profit_factor", "max_drawdown", "costs")}
            trials = 1
            if experiments is not None:
                experiments.log("backtest", {"model": P.PATH_VERSION, "min_edge": 0.10, "refit_days": 5},
                                INT.dataset_fingerprint(bars["M15"]), {"ev": r["ev_per_trade"], "trades": r["trades"]})
                trials = max(1, experiments.trials("backtest"))
            r["integrity"] = INT.deflated_sharpe(np.array(r.pop("trade_pnls")), trials)
            real.pop("trade_pnls", None)
            r["prediction_vs_profit_ar"] = ("نسبة النجاح (الوصول للهدف) ليست الربحية: الربحية تُقاس بالعائد المتوقع "
                                            "بعد التكاليف وفاصل ثقته وأقصى تراجع")
            r["note_ar"] = "فترة التطوير فقط. فترة الاختبار النهائية تُشغَّل عبر tools/run_final_backtest.py"
            return r
        return cached("backtest", build)

    @app.get("/research/micro-edge", dependencies=[Depends(auth)])
    def research_micro():
        def build():
            bars, label = research_bars()
            ds = P.build_path_dataset(bars["M15"], bars["H1"], bars["H4"])
            return {"dataset": label, **ME.discover(ds)}
        return cached("micro", build)

    @app.get("/research/info-value", dependencies=[Depends(auth)])
    def research_iv():
        def build():
            bars, label = research_bars()
            ds = P.build_path_dataset(bars["M15"], bars["H1"], bars["H4"])
            return {"dataset": label, **IV.ablation(ds)}
        return cached("iv", build)

    @app.get("/research/precision", dependencies=[Depends(auth)])
    def research_precision():
        """V3: calibration, meta-labeling, selective prediction + precision-coverage frontier, consensus,
        mixture of experts, dynamic barriers, robustness and the promotion gate (development period only)."""
        def build():
            bars, label = research_bars()
            return PREC.full_report(bars["M15"], bars["H1"], bars["H4"], label)
        return cached("precision", build)

    @app.get("/research/setups", dependencies=[Depends(auth)])
    def research_setups():
        from . import setups as SU
        def build():
            bars, label = research_bars()
            return {"dataset": label, **SU.evaluate(bars["M15"], bars["H1"], bars["H4"])}
        return cached("setups", build)

    @app.get("/research/feature-upgrade", dependencies=[Depends(auth)])
    def research_feature_upgrade():
        from .precision.feature_upgrade import compare
        def build():
            bars, label = research_bars()
            prov = "Dukascopy" if "Dukascopy" in label else "TwelveData"
            aux = {s_: history.load_bars(prov, s_, "M15") for s_ in ("XAGUSD", "EURUSD", "USDJPY")}
            aux = {k: v for k, v in aux.items() if len(v) > 1000}
            return compare(bars["M15"], bars["H1"], bars["H4"], aux or None, dataset_label=label)
        return cached("feature_upgrade", build)

    @app.get("/research/outlook", dependencies=[Depends(auth)])
    def research_outlook():
        """Historical validation of the WEEK / MONTH daily rules (fixed rules, non-overlapping, after costs)."""
        import dataclasses as _dc
        from . import outlook as OL
        def build():
            daily = history.load_bars("TwelveData", SYMBOL, "D1", limit=10_000)
            label = "LIVE HISTORY (TwelveData D1)"
            if len(daily) < OL.MIN_DAILY_BARS:
                daily = demo.bars("D1", demo.default_as_of(), 10_000).df
                label = "SYNTHETIC DEMO — اختبار للآلية فقط وليس دليلاً على أداء السوق"
            as_of = (daily.index[-1] + pd.Timedelta(days=1)).to_pydatetime()
            return {"dataset": label, "daily_bars": len(daily),
                    "rules": {v.horizon: {"rule_ar": OL.RULE_AR[v.horizon], "validated": v.validated,
                                          "current_action": v.action, "current_tilt": v.tilt,
                                          "stats": _dc.asdict(v.stats)} for v in OL.compute(daily, as_of)},
                    "note_ar": "النسبة تكرار تاريخي غير متداخل بعد التكاليف، وليست احتمالاً معايراً لصفقة بعينها"}
        return cached("outlook", build)

    @app.get("/outlooks/track", dependencies=[Depends(auth)])
    def outlooks_track():
        """Forward log written by the hourly CI job (models/outlook_track.json in the private repo)."""
        import json as _json
        p = repo_dir / "models" / "outlook_track.json"
        if not p.exists():
            return {"status": "EMPTY", "note_ar": "لم يُسجَّل شيء بعد — يبدأ السجل بعد أول تشغيل collect مع بيانات يومية"}
        return _json.loads(p.read_text(encoding="utf-8"))

    @app.get("/research/levels", dependencies=[Depends(auth)])
    def research_levels():
        """Out-of-sample validation of the support/resistance strength weights."""
        from . import levels as LV
        def build():
            bars, label = research_bars()
            as_of = (bars["H1"].index[-1] + pd.Timedelta(minutes=60)).to_pydatetime()
            m = LV.LevelService().model("research", bars, as_of)
            return {"dataset": label, "validation": m.validation, "features": LV.FEATURES,
                    "volume_used": False, "note_ar": "القوة ترتيب مئيني وليست احتمال ارتداد"}
        return cached("levels", build)

    @app.get("/research/granger", dependencies=[Depends(auth)])
    def research_granger():
        bars, label = research_bars()
        if not label.startswith("LIVE"):
            return {"status": "DISABLED", "reason_ar": "يتطلب تاريخ ذهب حقيقي وبيانات FRED — غير متاح في الوضع التجريبي"}
        ry = history.load_observations_as_of("FRED", "DFII10", utcnow())
        if ry.empty:
            return {"status": "DISABLED", "reason_ar": "بيانات FRED DFII10 غير مخزنة بعد"}
        g = bars["H4"]["close"].resample("1D").last().dropna()
        gr = np.log(g).diff()
        gr.index = gr.index.normalize()
        ry_s = pd.Series(ry["value"].to_numpy(), index=pd.to_datetime(ry["observed_at"], utc=True)).diff()
        both = pd.concat({"g": gr, "r": ry_s}, axis=1).dropna()
        return {"status": "OK", "dataset": label, "test": DIV.granger_stability(both["g"], both["r"])}

    return app
