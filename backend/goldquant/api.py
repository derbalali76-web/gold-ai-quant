"""FastAPI service.

Endpoints: /health /data-status /decision /history /model-metrics /engines /paper
           /research/backtest /research/micro-edge /research/info-value /research/granger
Research endpoints use stored LIVE history when enough exists, otherwise the labelled synthetic set.
Optional shared token: set GOLDQUANT_TOKEN and send header X-Goldquant-Token (all endpoints except /health).
"""
from __future__ import annotations

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
from fastapi import Depends, FastAPI, Header, HTTPException, Query

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
from .schemas import SCHEMA_VERSION, Decision, Mode
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
    cloud_on = bool(cs["repo"] and cs["token"]) and not mem
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
                          "last_sync_age_s": round(time.time() - sync_state["last"]) if sync_state["last"] else None}}

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

    def refresh_live(force: bool = False) -> Decision:
        with live_lock:  # one computation at a time; concurrent callers reuse its result
            if not force and live_cache["d"] is not None and time.time() - live_cache["t"] < LIVE_TTL:
                return live_cache["d"]
            d = attach_live_track(compute_live())
            live_cache.update(d=d, t=time.time())
            return d

    def live_loop():
        time.sleep(20)
        while True:
            try:
                refresh_live(force=time.time() - live_cache["t"] >= LIVE_TTL)
            except Exception:  # noqa: BLE001 — the next request/loop pass reports the real state
                pass
            time.sleep(max(30.0, LIVE_TTL / 2))

    if live_provider is not None and not mem and os.getenv("GOLDQUANT_BG_REFRESH", "1") == "1":
        threading.Thread(target=live_loop, daemon=True).start()

    crypto_state: dict = {"feed": None, "levels": None, "cache": {}}

    def crypto_decision(asset: str) -> Decision:
        from . import crypto_engine as CE
        from .levels import LevelService
        if crypto_state["feed"] is None:
            crypto_state["feed"], crypto_state["levels"] = CE.CryptoFeed(), LevelService()
        hit = crypto_state["cache"].get(asset)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        d = CE.decide(asset, crypto_state["feed"], utcnow(), crypto_state["levels"])
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

    def public_snapshot(d: Decision) -> dict:
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
        if live_provider is not None:
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
                "brief": d.daily_brief.model_dump(mode="json") if d.daily_brief else None, "bars": bars}

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
    def public_snapshot_ep():
        if live_provider is None:
            raise HTTPException(503, "no live data source")
        return public_snapshot(refresh_live())

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
