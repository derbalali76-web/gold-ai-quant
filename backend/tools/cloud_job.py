"""CI job for cloud mode (runs on GitHub Actions; see .github/workflows/cloud.yml).

    python tools/cloud_job.py collect   # hourly: live bars, related markets, Dukascopy daily, FRED/COT/GLD
    python tools/cloud_job.py train     # every few hours: train + validate path models -> models/
    python tools/cloud_job.py research  # daily: precision / setups / feature-upgrade reports -> models/
    python tools/cloud_job.py backfill --years 3   # one-off: Dukascopy history

Works on the checked-out repository: reads and writes ./market_data and ./models (env GOLDQUANT_REPO_ROOT).
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from goldquant import cloud  # noqa: E402
from goldquant.context import ContextService, MACRO_SERIES  # noqa: E402
from goldquant.providers.dukascopy import DukascopyImporter, to_timeframe  # noqa: E402
from goldquant.providers.history import HistoryStore  # noqa: E402
from goldquant.providers.twelvedata import TwelveDataProvider, parse_time_series  # noqa: E402

ROOT = Path(os.environ.get("GOLDQUANT_REPO_ROOT", Path(__file__).resolve().parents[2]))
MD, MODELS = ROOT / "market_data", ROOT / "models"
DUKA = ("XAUUSD", "XAGUSD", "EURUSD", "USDJPY", "DOLLARIDXUSD", "USA500IDXUSD", "USTBONDTRUSD")
AUX_TD = {"EUR/USD": "EURUSD", "USD/JPY": "USDJPY", "XAG/USD": "XAGUSD"}
TFS = {"M15": 15, "H1": 60, "H4": 240}


def load() -> HistoryStore:
    hs = HistoryStore()
    print("loaded:", cloud.import_tree(hs, MD))
    return hs


def save(hs: HistoryStore) -> None:
    cloud.export_bars(hs, MD, "TwelveData", "XAU/USD", "D1")
    for provider, symbols in (("TwelveData", ["XAU/USD"] + list(AUX_TD.values())), ("Dukascopy", list(DUKA))):
        for sym in symbols:
            for tf in TFS:
                cloud.export_bars(hs, MD, provider, sym, tf)
    for s in MACRO_SERIES:
        cloud.export_observations(hs, MD, "FRED", s)
    cloud.export_observations(hs, MD, "SPDR", "GLD_TONNES")


def store_duka(hs: HistoryStore, sym: str, m1: pd.DataFrame) -> None:
    if m1.empty:
        return
    now = datetime.now(timezone.utc)
    for tf, mins in TFS.items():
        hs.upsert_bars("Dukascopy", sym, tf, to_timeframe(m1, mins), now)


def collect(hs: HistoryStore) -> None:
    now = datetime.now(timezone.utc)
    key = os.environ.get("TWELVEDATA_API_KEY", "")
    if key:
        td = TwelveDataProvider(key, hs)
        for tf in list(TFS) + ["D1"]:  # D1: ~20 years in the first call (1 credit), then small top-ups
            try:
                td.refresh(tf, now)
            except Exception as exc:  # noqa: BLE001
                print("TD", tf, exc)
        for td_sym, name in AUX_TD.items():  # related markets: M15 only (credit budget)
            try:
                r = td.http.get("https://api.twelvedata.com/time_series", {
                    "symbol": td_sym, "interval": "15min", "outputsize": 300, "timezone": "UTC", "apikey": key})
                df = parse_time_series(r.text)
                df = df[df.index + pd.Timedelta(minutes=15) <= pd.Timestamp(now)]
                hs.upsert_bars("TwelveData", name, "M15", df, now)
            except Exception as exc:  # noqa: BLE001
                print("TD aux", td_sym, exc)
        try:  # credit monitoring (shared by this job AND the web service): kept for the weekly report
            u = json.loads(td.http.get("https://api.twelvedata.com/api_usage", {"apikey": key}).text)
            rec = {"at": now.isoformat(), "daily_usage": u.get("daily_usage"), "plan_daily_limit": u.get("plan_daily_limit")}
            log = MODELS / "td_usage.jsonl"
            MODELS.mkdir(parents=True, exist_ok=True)
            lines = (log.read_text(encoding="utf-8").splitlines() if log.exists() else [])[-335:]
            log.write_text("\n".join(lines + [json.dumps(rec)]) + "\n", encoding="utf-8")
            print("TD credits:", rec)
        except Exception as exc:  # noqa: BLE001
            print("TD usage check failed:", exc)
    imp = DukascopyImporter()
    for sym in DUKA:  # yesterday + today-so-far (closed minutes only)
        try:
            m1 = imp.fetch_range(sym, (now - timedelta(days=1)).date(), (now - timedelta(days=1)).date())
            store_duka(hs, sym, m1)
        except Exception as exc:  # noqa: BLE001
            print("Duka", sym, exc)
    auto_cal = MODELS / "calendar_auto.json"
    try:  # refresh the official calendar at most every 6 hours (BLS updates weekly, Fed yearly)
        age = now - datetime.fromtimestamp(auto_cal.stat().st_mtime, timezone.utc) if auto_cal.exists() else None
        old = json.loads(auto_cal.read_text(encoding="utf-8")).get("updated_at") if auto_cal.exists() else None
        stale = old is None or now - datetime.fromisoformat(old.replace("Z", "+00:00")) > timedelta(hours=6)
        if stale or age is None:
            from goldquant.sources import calendar_auto
            print("calendar:", calendar_auto.refresh(auto_cal, now))
    except Exception as exc:  # noqa: BLE001 — never fatal; the calendar simply ages
        print("calendar refresh failed:", exc)
    try:  # point-in-time consensus forecasts (future "surprise" feature): market_data/calendar/ff_forecasts.jsonl
        from goldquant.sources import ff_calendar
        print("forecasts:", ff_calendar.refresh(MD / "calendar" / "ff_forecasts.jsonl", now))
    except Exception as exc:  # noqa: BLE001
        print("forecast recorder failed:", exc)
    ctx = ContextService(hs, ROOT / "config" / "calendar.json", auto_calendar_path=auto_cal)
    ctx.refresh(now)
    outlook_forward_log(hs, now)
    if key:
        try:
            hours_forward_log(hs, td, ctx, now)
        except Exception as exc:  # noqa: BLE001 — never fatal for data collection
            print("hours forward log failed:", exc)
    for r in hs.recent_fetches(40):
        print(r)


def outlook_forward_log(hs: HistoryStore, now: datetime) -> None:
    """Append today's WEEK/MONTH outlook and resolve matured ones (persistent: committed under models/)."""
    from goldquant import outlook_log as OLOG
    daily = hs.load_bars("TwelveData", "XAU/USD", "D1", limit=10_000)
    if len(daily) < 300:
        print("outlook log: daily history too short", len(daily))
        return
    log = MODELS / "outlook_log.jsonl"
    new = OLOG.append_today(daily, now, log)
    track = OLOG.resolve(OLOG.read_log(log), daily)
    MODELS.mkdir(parents=True, exist_ok=True)
    (MODELS / "outlook_track.json").write_text(json.dumps(track, ensure_ascii=False, indent=1), encoding="utf-8")
    print("outlook log: +", len(new), {k: v["resolved"] for k, v in track["horizons"].items()})


def hours_forward_log(hs: HistoryStore, td, ctx, now: datetime) -> None:
    """Persistent paper ledger for the HOURS horizon, run by the hourly CI job with the same model and gates as the
    server: every BUY/SELL is recorded before its outcome is known, then resolved on later M15 bars (pending orders that
    never fill are NOT counted). Survives server restarts because it lives in the private repository."""
    import shutil
    import tempfile
    from goldquant import paper as PAPER
    from goldquant.engine import DecisionEngine
    from goldquant.precision.production import PrecisionService
    from goldquant.risk import EST_SLIPPAGE, EST_SPREAD
    from goldquant.schemas import Mode
    from goldquant.store import Store
    state, _ = cloud.load_path_state(MODELS)
    tmp = Path(tempfile.mkdtemp())
    for f in ("precision_report.json", "promotions.json"):
        if (MODELS / f).exists():
            shutil.copy(MODELS / f, tmp / f)
    log = MODELS / "hours_paper.jsonl"
    ledger = PAPER.PaperLedger(":memory:")
    if log.exists():
        PAPER.import_rows(ledger, [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()])
    eng = DecisionEngine(Store(":memory:"), precision=PrecisionService(tmp), ledger=ledger)
    if state is not None:
        eng.paths.set_prebuilt(state)
    d = eng.decide(td, Mode.LIVE, now, ctx.snapshot(now))
    ledger.record(d)
    m15 = td.bars("M15", now, 2000)
    if m15 is not None:
        ledger.resolve(m15.df, now, cost=EST_SPREAD + EST_SLIPPAGE)  # results after estimated costs
    rows = PAPER.export_rows(ledger)
    log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    st = PAPER.perf(rows)
    (MODELS / "hours_track.json").write_text(json.dumps({"generated_at": now.isoformat(), "HOURS": st}, indent=1),
                                            encoding="utf-8")
    print("hours forward log:", d.action.value, st)


BACKFILL_BUDGET = timedelta(minutes=70)  # the workflow is killed at 120 min: stop early and SAVE what we have


def backfill(hs: HistoryStore, years: float, first: date | None = None, last: date | None = None,
             budget_min: float | None = None, symbols: tuple | None = None) -> None:
    """Newest data first, gold first; stops before the CI time limit so the commit step always runs.
    Re-running backfill continues where the previous run stopped (already-stored months are skipped)."""
    import time
    t0 = time.monotonic()
    imp = DukascopyImporter()
    end = last or (date.today() - timedelta(days=1))
    start = first or (end - timedelta(days=int(365 * years)))
    budget = timedelta(minutes=budget_min) if budget_min else BACKFILL_BUDGET
    for sym in (symbols or DUKA):
        d = end
        while d >= start:
            if time.monotonic() - t0 > budget.total_seconds():
                print("time budget reached — saving; run backfill again to continue", flush=True)
                return
            chunk_start = max(start, d - timedelta(days=30))
            have = hs.load_bars("Dukascopy", sym, "H1", limit=10_000_000)
            n_have = len(have[(have.index >= pd.Timestamp(chunk_start, tz="UTC")) &
                              (have.index < pd.Timestamp(d + timedelta(days=1), tz="UTC"))]) if len(have) else 0
            if n_have >= 400:  # ~ a full month of H1 bars already stored
                d = chunk_start - timedelta(days=1)
                continue
            m1 = imp.fetch_range(sym, chunk_start, d)
            store_duka(hs, sym, m1)
            save(hs)  # persist every chunk so a kill never loses finished months
            print(sym, chunk_start, d, len(m1), "errors:", len(imp.errors), imp.errors[-2:], flush=True)
            d = chunk_start - timedelta(days=1)


def training_bars(hs: HistoryStore):
    """One consistent feed for training: Dukascopy if long and current, else Twelve Data."""
    duka = {tf: hs.load_bars("Dukascopy", "XAUUSD", tf) for tf in TFS}
    td = {tf: hs.load_bars("TwelveData", "XAU/USD", tf) for tf in TFS}
    fresh = lambda b: len(b["M15"]) and (pd.Timestamp.now(tz="UTC") - b["M15"].index[-1]) < pd.Timedelta(days=4)  # noqa
    if len(duka["M15"]) >= 4000 and fresh(duka) and len(duka["M15"]) >= len(td["M15"]):
        return duka, "LIVE HISTORY (Dukascopy)"
    return td, "LIVE HISTORY (TwelveData)"


CRYPTO_START = {"BTCUSDT": (2018, 1), "ETHUSDT": (2018, 1), "SOLUSDT": (2020, 9)}


def crypto(budget_min: float | None = None) -> None:
    """Binance public archive -> market_data/crypto: 1h + 1d klines (real + taker-buy volume) and perp funding.
    Already complete months are skipped; the current month comes from the daily files."""
    import time
    from goldquant import crypto_store as CS
    from goldquant.providers.binance_archive import BinanceArchive, months
    t0, arc = time.monotonic(), BinanceArchive()
    today = date.today()
    last_full = (today.replace(day=1) - timedelta(days=1))
    for sym, (y0, m0) in CRYPTO_START.items():
        for tf, rows in (("1h", 600), ("1d", 25), ("15m", 2600)):
            first = date(y0, m0, 1) if tf != "15m" else max(date(y0, m0, 1), date(2021, 1, 1))  # scalping lab
            for y, m in months(first, last_full):
                if budget_min and time.monotonic() - t0 > budget_min * 60:
                    print("crypto: time budget reached")
                    return
                if CS.have_month(MD, sym, tf, y, m, rows):
                    continue
                df = arc.klines_month(sym, tf, y, m)
                print(sym, tf, f"{y}-{m:02d}", len(df), CS.save_bars(MD, sym, tf, df), flush=True)
            d = today.replace(day=1)
            parts = []
            while d < today:  # current month so far (daily archive files appear the next day)
                parts.append(arc.klines_day(sym, tf, d))
                d += timedelta(days=1)
            parts = [p for p in parts if len(p)]
            if parts:
                CS.save_bars(MD, sym, tf, pd.concat(parts))
        for y, m in months(date(max(y0, 2019), m0 if y0 >= 2019 else 9, 1), last_full):
            p = MD / "crypto" / sym / "funding" / f"{y:04d}.csv.gz"
            if p.exists() and (y < today.year) and len(CS.read(p)) >= 1000:
                continue
            CS.save_funding(MD, sym, arc.funding_month(sym, y, m))
    # USD-M futures metrics (open interest, top-trader and taker long/short ratios): daily files, kept hourly
    import calendar
    for sym in CRYPTO_START:
        for y, m in months(date(2022, 1, 1), today):
            if budget_min and time.monotonic() - t0 > budget_min * 60:
                print("crypto: time budget reached (metrics)")
                return
            ndays = calendar.monthrange(y, m)[1]
            last_day = min(ndays, (today - timedelta(days=1)).day) if (y, m) == (today.year, today.month) else ndays
            if CS.metrics_days_have(MD, sym, y, m) >= last_day * 24 * 0.95:
                continue
            parts = [arc.metrics_day(sym, date(y, m, dd)) for dd in range(1, last_day + 1)]
            parts = [p for p in parts if len(p)]
            if parts:
                print(sym, "metrics", f"{y}-{m:02d}", CS.save_metrics(MD, sym, pd.concat(parts)), flush=True)
    print("crypto archive errors:", len(arc.errors), arc.errors[-3:])


def crypto_research() -> dict:
    """Walk-forward for each coin: HOURS on 1h bars (base vs + real-volume / funding features, same period),
    WEEK / MONTH on 1d bars. Reported only — a coin gets recommendations only if a horizon qualifies."""
    from dataclasses import asdict
    from goldquant import crypto_store as CS, data_quality as DQ
    from goldquant import planner as PLN
    now = datetime.now(timezone.utc)
    out = {"generated_at": now.isoformat(), "assets": {}}
    for sym in CRYPTO_START:
        h1, d1 = CS.load_bars(MD, sym, "1h"), CS.load_bars(MD, sym, "1d")
        h1 = h1[h1.index >= pd.Timestamp("2021-01-01", tz="UTC")]  # 5+ years of H1 is plenty; keeps CI under its limit
        fund = CS.load_funding(MD, sym)
        fast = {"min_train": 4380, "test_block": 2190}  # 6 months of training, refit every quarter
        if len(h1) < 5000:
            continue
        a = {"bars_1h": len(h1), "first": str(h1.index[0]), "last": str(h1.index[-1]),
             "data_quality": DQ.check_bars(h1, "1h", now, None, market="crypto")}
        base_cols = PLN.FEATURES + PLN.INTRADAY
        rp = PLN.walk_forward(h1, "HOURS", cols=base_cols, asset=sym + "_PERP", **fast)
        a["HOURS"] = a["HOURS_perp"] = asdict(rp)  # perpetual cost (the cheaper realistic venue) is the reference
        print(sym, "HOURS perp", rp.trades, rp.expectancy_pct, rp.baseline_expectancy_pct, rp.reason, flush=True)
        met = CS.load_metrics(MD, sym)
        starts = [h1.index[0]] + ([fund.index[0]] if len(fund) else []) + ([met.index[0]] if len(met) else [])
        since = str(max(starts) + pd.Timedelta(days=30))[:10]
        hx = h1.join(met, how="left") if len(met) else h1
        cb = PLN.walk_forward(hx, "HOURS", cols=base_cols, asset=sym + "_PERP", since=since, **fast)
        extra = PLN.FLOW + (PLN.METRICS if len(met) else [])
        cf = PLN.walk_forward(hx, "HOURS", cols=base_cols + extra, asset=sym + "_PERP", since=since,
                              funding=fund if len(fund) else None, **fast)
        a["HOURS_flow_ab"] = {"since": since, "cost": "perp", "features": extra, "base": asdict(cb), "flow": asdict(cf)}
        print(sym, "HOURS perp A/B", since, "| base", cb.expectancy_pct, cb.direction_accuracy, cb.reason,
              "| flow+metrics", cf.expectancy_pct, cf.direction_accuracy, cf.reason, flush=True)
        # ETH / SOL: Bitcoin's own recent moves as a leading market (same period, same cost as the reference)
        if sym != "BTCUSDT":
            btc = CS.load_bars(MD, "BTCUSDT", "1h")
            bb = rp
            bx = PLN.walk_forward(h1, "HOURS", cols=base_cols + PLN.cross_cols(["BTCUSDT"]), asset=sym + "_PERP",
                                  aux={"BTCUSDT": btc}, **fast)
            a["HOURS_btc_lead_ab"] = {"base": asdict(bb), "btc_lead": asdict(bx)}
            print(sym, "HOURS BTC-lead A/B | base", bb.expectancy_pct, bb.reason, "| +BTC", bx.expectancy_pct, bx.reason,
                  flush=True)
        if len(d1) > 1300:
            for hz in PLN.DAILY_HZ:
                r = PLN.walk_forward(d1, hz, asset=sym)
                a[hz] = asdict(r)
                rq = PLN.walk_forward(d1, hz, asset=sym + "_PERP")
                a[hz + "_perp"] = asdict(rq)
                a[hz + "_regimes"] = {rg: asdict(PLN.walk_forward(d1, hz, asset=sym + "_PERP", regime=rg))
                                      for rg in PLN.REGIMES}
                print(sym, hz, "spot", r.expectancy_pct, r.baseline_expectancy_pct, r.reason, "| perp", rq.expectancy_pct,
                      rq.baseline_expectancy_pct, rq.reason, flush=True)
        out["assets"][sym] = a
    from goldquant import scalp as SC
    for sym in CRYPTO_START:  # scalping lab on 15-min bars: user's Binance cost (0.075 % per side with BNB)
        m15 = CS.load_bars(MD, sym, "15m")
        if len(m15) > 20000 and sym in out["assets"]:
            fund = CS.load_funding(MD, sym)
            if len(fund):
                mm = pd.merge_asof(pd.DataFrame({"t": m15.index + pd.Timedelta(minutes=15)}),
                                   pd.DataFrame({"t": fund.index, "funding": fund["funding"].to_numpy()}),
                                   on="t", direction="backward")
                m15 = m15.assign(funding=mm["funding"].to_numpy())
            out["assets"][sym]["scalp"] = {"cost": 0.0015, "results": SC.run_all(m15, 0.0015) + SC.run_all(
                m15, 0.0015, rules=SC.CRYPTO_RULES2 + SC.CRYPTO_RULES3, ci_level=SC.CI_ROUND2)}
            for r in out["assets"][sym]["scalp"]["results"]:
                print(sym, "scalp", r["rule"], r["stop"], r["trades"], r["avg_net_pct"], r["reason"], flush=True)
    out["activity"] = activity_models()
    (MODELS / "crypto_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                               encoding="utf-8")
    return out


def ensure_1m(budget_min: float) -> tuple:
    """Download missing 1-minute months into the CI cache folder (SCALP_DATA). Returns (root, complete, symbols)."""
    import time
    from goldquant import crypto_store as CS
    from goldquant.providers.binance_archive import BinanceArchive, months
    root = Path(os.environ.get("SCALP_DATA", ROOT / "cache_1m"))
    t0, arc = time.monotonic(), BinanceArchive()
    today = date.today()
    last_full = today.replace(day=1) - timedelta(days=1)
    syms = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
    complete = True
    for a, sym in syms.items():
        for y, m in months(date(2021, 1, 1), last_full):
            if time.monotonic() - t0 > budget_min * 60:
                complete = False
                break
            if CS.have_month(root, sym, "1m", y, m, 38000):
                continue
            df = arc.klines_month(sym, "1m", y, m)
            print(a, "1m", f"{y}-{m:02d}", len(df), CS.save_bars(root, sym, "1m", df), flush=True)
        d = today.replace(day=1)
        parts = []
        while d < today and complete:
            parts.append(arc.klines_day(sym, "1m", d))
            d += timedelta(days=1)
        parts = [p for p in parts if len(p)]
        if parts:
            CS.save_bars(root, sym, "1m", pd.concat(parts))
    return root, complete, syms


def scalp_feasibility(budget_min: float = 75) -> dict:
    """Base-rate study of the +0.65 % target (goldquant/scalp_feasibility.py)."""
    from goldquant import crypto_store as CS, scalp1m as S1, scalp_feasibility as SF
    root, complete, syms = ensure_1m(budget_min * 0.45)
    out = {"updated_at": datetime.now(timezone.utc).isoformat(), "data_complete": complete, "assets": {}}
    for a, sym in syms.items():
        d = CS.load_bars(root, sym, "1m")
        if len(d) < 100_000:
            continue
        gate, act = S1.activity_gate(d)
        r = SF.study(d, a, gate.astype(int))
        r["activity_forecast"] = act
        out["assets"][a] = r
        for x in r["fixed"]:
            print(a, "fixed", x, flush=True)
        for x in r["dynamic"]:
            print(a, "dynamic", x, flush=True)
        print(a, "activity", r["by_activity"], flush=True)
    (MODELS / "scalp_feasibility.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                   encoding="utf-8")
    return out


def scalp_ml(budget_min: float = 75) -> dict:
    """Scalping experiment 2: P(target before stop) models (goldquant/scalp_ml.py, pre-registered)."""
    import time
    from goldquant import crypto_store as CS, scalp1m as S1, scalp_ml as SM
    t0 = time.monotonic()
    root, complete, syms = ensure_1m(budget_min * 0.3)
    out = {"version": SM.VERSION, "updated_at": datetime.now(timezone.utc).isoformat(), "data_complete": complete,
           "assets": {}}
    for a, sym in syms.items():
        if time.monotonic() - t0 > budget_min * 60 * 0.85:
            print("scalp_ml: time budget reached before", a, flush=True)
            break
        d = CS.load_bars(root, sym, "1m")
        if len(d) < 100_000:
            continue
        gate, _ = S1.activity_gate(d)
        fund = CS.load_funding(MD, sym)
        out["assets"][a] = SM.run_asset(d, a, fund if len(fund) else None, gate.astype(int))
        for r in out["assets"][a]:
            print(a, "ml", r["model"], r.get("implementation"), r["window_min"], r["stop_pct"], "thr", r["threshold_p"],
                  "maxp", r.get("max_p"), "trades", r.get("trades"), "avg", r.get("avg_net_pct"), r.get("avg_net_ci"),
                  "ho", r.get("holdout_avg_pct"), "even", r.get("baseline_even_avg_pct"), "act",
                  r.get("baseline_activity_avg_pct"), r["reason"], flush=True)
        (MODELS / "scalp_ml_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                     encoding="utf-8")
    return out


def ensure_book(root: Path, syms: dict, budget_min: float) -> dict:
    """Futures order-book depth snapshots, one monthly csv.gz per coin in the CI cache (never in git)."""
    import calendar
    import time
    from goldquant.providers.binance_archive import BinanceArchive, months
    t0, arc = time.monotonic(), BinanceArchive()
    today = date.today()
    books = {}
    for a, sym in syms.items():
        folder = root / "crypto" / sym / "book"
        folder.mkdir(parents=True, exist_ok=True)
        for y, m in months(date(2022, 1, 1), today):
            f = folder / f"{y:04d}-{m:02d}.csv.gz"
            current = (y, m) == (today.year, today.month)
            if (f.exists() and not current) or (folder / f"{y:04d}-{m:02d}.none").exists():
                continue
            if time.monotonic() - t0 > budget_min * 60:
                print("book: time budget reached", flush=True)
                break
            last = (today - timedelta(days=1)).day if current else calendar.monthrange(y, m)[1]
            parts = [arc.book_depth_day(sym, date(y, m, dd)) for dd in range(1, last + 1)]
            parts = [p_ for p_ in parts if len(p_)]
            if not parts:
                if not current:
                    (folder / f"{y:04d}-{m:02d}.none").write_text("not published")
                continue
            pd.concat(parts).to_csv(f, compression="gzip")
            print(a, "book", f"{y}-{m:02d}", sum(len(p_) for p_ in parts), flush=True)
        files = sorted(folder.glob("*.csv.gz"))
        if files:
            b = pd.concat([pd.read_csv(x, index_col=0) for x in files])
            b.index = pd.to_datetime(b.index, utc=True)
            books[a] = b.sort_index()
    print("book archive errors:", len(arc.errors), arc.errors[-3:], flush=True)
    return books


def scalp_book(budget_min: float = 120) -> dict:
    """Scalping experiment 3: does order-book depth add information? (goldquant/scalp_ml.py, pre-registered)."""
    from goldquant import crypto_store as CS, scalp1m as S1, scalp_ml as SM
    root, complete, syms = ensure_1m(budget_min * 0.15)
    books = ensure_book(root, syms, budget_min * 0.45)
    out = {"doc": SM.BOOK_DOC, "updated_at": datetime.now(timezone.utc).isoformat(), "assets": {}}
    for a, sym in syms.items():
        if a not in books or len(books[a]) < 10000:
            print(a, "no usable book data", flush=True)
            continue
        d = CS.load_bars(root, sym, "1m")
        gate, _ = S1.activity_gate(d)
        fund = CS.load_funding(MD, sym)
        print(a, "book rows", len(books[a]), books[a].index[0], books[a].index[-1], flush=True)
        r = SM.run_book(d, a, books[a], fund if len(fund) else None, gate.astype(int))
        out["assets"][a] = r
        for x in r["results"]:
            print(a, "book", x["model"], x["window_min"], x["stop_pct"], "maxp", x.get("max_p"), "trades", x.get("trades"),
                  "avg", x.get("avg_net_pct"), x.get("avg_net_ci"), "ho", x.get("holdout_avg_pct"), x["reason"][:80],
                  flush=True)
        print(a, "book value", r["book_value"], flush=True)
        (MODELS / "scalp_book_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                       encoding="utf-8")
    return out


def scalp1m(budget_min: float = 75) -> dict:
    """1-minute scalping engine (goldquant/scalp1m.py, pre-registered). 1-min data is large, so it lives in a CI
    cache folder (SCALP_DATA), never in git; only the report is committed."""
    import time
    from goldquant import crypto_store as CS, scalp1m as S1
    t0 = time.monotonic()
    root, complete, syms = ensure_1m(budget_min * 0.45)
    out = {"schema": 1, "version": S1.VERSION, "updated_at": datetime.now(timezone.utc).isoformat(),
           "data_complete": complete, "assets": {}, "fee_sensitivity": {}}
    for a, sym in syms.items():
        d = CS.load_bars(root, sym, "1m")
        print(a, "1m bars", len(d), d.index[0] if len(d) else None, flush=True)
        if len(d) < 100_000:
            continue
        out["assets"][a] = S1.run_asset(d, a)
        for r in out["assets"][a]:
            print(a, r["setup"], r["stop"], "orders", r["orders"], "filled", r["filled"], "avg", r["avg_net_pct"],
                  "ho", r["holdout_avg_pct"], "base", r["baseline_avg_pct"], "dd", r["max_drawdown_pct"],
                  r["reason"], flush=True)
        r4 = S1.run_round4(d, a)
        out.setdefault("round4", {"doc": S1.ROUND4_DOC, "assets": {}})["assets"][a] = r4
        print(a, "round4 activity", r4["activity_forecast"], "gate share", r4["gate_share"], flush=True)
        for r in r4["results"]:
            print(a, "r4", r["setup"], r["stop"], "filled", r["filled"], "avg", r["avg_net_pct"], "ho", r["holdout_avg_pct"],
                  "base", r["baseline_avg_pct"], r["reason"], flush=True)
        if time.monotonic() - t0 < budget_min * 60 * 0.8:
            out["fee_sensitivity"][a] = S1.fee_sensitivity(d, a)
    (MODELS / "scalp1m_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                encoding="utf-8")
    return out


def pooled_research(hs: HistoryStore) -> dict:
    """Multi-asset tournament (goldquant/pooled.py, pre-registered). Gathers the panel (own stores + FRED + COT)."""
    import io
    from goldquant import crypto_store as CS, pooled as PO
    from goldquant.providers.http import HttpClient, RateLimiter
    http = HttpClient(limiter=RateLimiter(calls=20, period=60.0), retries=2, backoff=2.0, timeout=60.0)
    closes, cots = {}, {}
    d = hs.load_bars("TwelveData", "XAU/USD", "D1", limit=10_000)
    if len(d):
        closes["XAU"] = d["close"]
    for sym, a in (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH"), ("SOLUSDT", "SOL")):
        c = CS.load_bars(MD, sym, "1d")
        if len(c):
            closes[a] = c["close"]
    for sym, a in PO.DUKA_ASSETS.items():
        h = hs.load_bars("Dukascopy", sym, "H1", limit=10_000_000)
        if len(h):
            closes[a] = h["close"].resample("1D").last().dropna()
    cache = MD / "pooled"
    cache.mkdir(parents=True, exist_ok=True)
    for sid, (a, inv) in PO.FRED_ASSETS.items():
        f = cache / f"fred_{sid}.csv"
        try:
            r = http.get("https://fred.stlouisfed.org/graph/fredgraph.csv", {"id": sid, "cosd": "2006-01-01"})
            f.write_text(r.text, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print("FRED", sid, "failed:", exc, "(using cache)" if f.exists() else "", flush=True)
        if f.exists():
            t = pd.read_csv(f)
            t[sid] = pd.to_numeric(t[sid], errors="coerce")
            t = t.dropna()
            ser = pd.Series(t[sid].to_numpy(float), index=pd.to_datetime(t[t.columns[0]], utc=True))
            closes[a] = 1.0 / ser if inv else ser
    for a, (ds, code) in PO.COT_MAP.items():
        f = cache / f"cot_{a}.json"
        try:
            r = http.get(f"https://publicreporting.cftc.gov/resource/{ds}.json",
                         {"cftc_contract_market_code": code, "$order": "report_date_as_yyyy_mm_dd", "$limit": 5000})
            f.write_text(r.text, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print("COT", a, "failed:", exc, "(using cache)" if f.exists() else "", flush=True)
        if f.exists():
            cots[a] = PO.parse_cot_rows(json.loads(f.read_text(encoding="utf-8")))
            print("COT", a, len(cots[a]), cots[a]["report"].iloc[0].date() if len(cots[a]) else None, flush=True)
    for a, s_ in closes.items():
        print("panel", a, len(s_), s_.index[0].date(), s_.index[-1].date(), flush=True)
    out = PO.tournament(closes, cots)
    out["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        out["round2"] = PO.tournament_round2(closes, cots)
        for r in out["round2"]["results"]:
            print("pooled-2", r["horizon"], r["asset"], r["model"], r.get("avg_net_pct"), r.get("avg_net_ci"), "ALall",
                  r.get("always_long_all_days_pct"), "edgeAll", r.get("edge_vs_long_all_days_ci"), r["reason"], flush=True)
        print("COT value", out["round2"]["cot_value"], flush=True)
    except ImportError as exc:
        print("round 2 needs lightgbm:", exc, flush=True)
    for r in out["results"]:
        print("pooled", r["horizon"], r["asset"], r["model"], r.get("trades"), r.get("avg_net_pct"), r.get("avg_net_ci"),
              "long", r.get("always_long_avg_pct"), "single", r.get("single_asset_avg_pct"), "ho",
              r.get("holdout_avg_pct"), r["reason"], flush=True)
    (MODELS / "pooled_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                               encoding="utf-8")
    return out


def scenario_history(hs) -> dict:
    """Daily: descriptive history of scenario breaks (goldquant/brief.py) over the last two years of H1 bars."""
    from goldquant import brief as BR, crypto_store as CS
    out = {"updated_at": datetime.now(timezone.utc).isoformat(), "assets": {}}
    two_years = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=730)
    frames = {"XAU": hs.load_bars("Dukascopy", "XAUUSD", "H1", limit=10_000_000) if hs is not None else None}
    for sym, a in (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH"), ("SOLUSDT", "SOL")):
        frames[a] = CS.load_bars(MD, sym, "1h")
    for a, h1 in frames.items():
        if h1 is None or len(h1) < 2000:
            continue
        out["assets"][a] = BR.history_table(h1[h1.index >= two_years])
    (MODELS / "scenario_history.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("scenario history:", {a: v["days"] for a, v in out["assets"].items()}, flush=True)
    return out


def touch_models(hs) -> dict:
    """Touch probability (goldquant/touch.py, pre-registered): validate per asset and horizon; export qualified ones."""
    from goldquant import crypto_store as CS, touch as TO
    out = {"schema": 1, "updated_at": datetime.now(timezone.utc).isoformat(), "assets": {}}
    frames = {"XAU": hs.load_bars("Dukascopy", "XAUUSD", "H1", limit=10_000_000) if hs is not None else None}
    for sym, a in (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH"), ("SOLUSDT", "SOL")):
        frames[a] = CS.load_bars(MD, sym, "1h")
    for a, h1 in frames.items():
        if h1 is None or len(h1) < 8000:  # ~1.5 years of gold trading hours: enough for at least two yearly folds
            print(a, "touch: not enough hourly bars", 0 if h1 is None else len(h1), flush=True)
            continue
        rep = TO.evaluate_asset(h1)
        out["assets"][a] = {h: {"report": r, "model": TO.export(h1, int(h)) if r.get("qualified") else None}
                            for h, r in rep.items()}
        for h, r in rep.items():
            print(a, h, "touch", {k: r.get(k) for k in ("skill", "skill_ci99.9", "holdout_skill", "reason")}, flush=True)
    (MODELS / "touch_models.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return out


def range_research(hs) -> dict:
    """Price-range engine (goldquant/price_range.py, pre-registered): each asset and horizon separately.
    Event windows use FOMC decisions + BLS releases fetched now (descriptive only; not a gate)."""
    from goldquant import crypto_store as CS, price_range as PR
    from goldquant.sources import calendar_auto as CA
    from goldquant.providers.http import HttpClient, RateLimiter
    events, ev_src = [], {}
    http = HttpClient(limiter=RateLimiter(calls=4, period=10.0))
    for name, url, parse in (("fomc", CA.FOMC_URL, CA.parse_fomc_html), ("bls", CA.BLS_ICS, CA.parse_bls_ics)):
        try:
            got = parse(http.get(url).text)
            events += [e["time_utc"] for e in got if e.get("importance", 0) >= 3]
            ev_src[name] = len(got)
        except Exception as exc:  # noqa: BLE001 — events are descriptive; their absence is reported, not hidden
            ev_src[name] = f"unavailable: {str(exc)[:80]}"
    out = {"schema": 1, "version": PR.VERSION, "updated_at": datetime.now(timezone.utc).isoformat(),
           "events_source": ev_src, "events_n": len(events), "assets": {}}
    models = {"schema": 1, "version": PR.VERSION, "updated_at": out["updated_at"], "assets": {}}
    frames = {"XAU": ("gold", hs.load_bars("Dukascopy", "XAUUSD", "H1", limit=10_000_000))}
    for sym, a in (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH"), ("SOLUSDT", "SOL")):
        frames[a] = ("crypto", CS.load_bars(MD, sym, "1h"))
    for a, (kind, h1) in frames.items():
        if h1 is None or len(h1) < 8000:
            out["assets"][a] = {"reason": "not enough hourly bars"}
            continue
        out["assets"][a] = PR.evaluate_asset(h1, kind, events)
        models["assets"][a] = {h: {"qualified": bool(r.get("qualified")), "reason": r.get("reason"),
                                   "holdout_coverage": (r.get("holdout") or {}).get("m", {}).get("coverage"),
                                   "params": PR.export(h1, kind, h)} for h, r in out["assets"][a].items()}
        for h, r in out["assets"][a].items():
            print(a, h, r.get("reason"), {k: r.get(k) for k in ("score_diff_vs_best", "score_diff_ci99")},
                  (r.get("holdout") or {}).get("m"), flush=True)
    (MODELS / "range_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    # live parameters for every asset x horizon (the ledger records all of them; the app shows qualified ones only)
    (MODELS / "range_models.json").write_text(json.dumps(models, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return out


PAXG = "PAXGUSDT"
PAXG_START = (2019, 9)


def paxg_download(budget_min: float = 40) -> None:
    """Binance public archive -> market_data/crypto/PAXGUSDT (1h + 1d spot klines). Separate from CRYPTO_START so no
    existing crypto research picks it up before its own pre-registration."""
    import time
    from goldquant import crypto_store as CS
    from goldquant.providers.binance_archive import BinanceArchive, months
    t0, arc = time.monotonic(), BinanceArchive()
    today = date.today()
    last_full = today.replace(day=1) - timedelta(days=1)
    for tf, rows in (("1h", 600), ("1d", 25)):
        for y, m in months(date(*PAXG_START, 1), last_full):
            if time.monotonic() - t0 > budget_min * 60:
                print("paxg: time budget reached")
                return
            if CS.have_month(MD, PAXG, tf, y, m, rows):
                continue
            df = arc.klines_month(PAXG, tf, y, m)
            if len(df):
                print(PAXG, tf, f"{y}-{m:02d}", len(df), CS.save_bars(MD, PAXG, tf, df), flush=True)
        d, parts = today.replace(day=1), []
        while d < today:
            parts.append(arc.klines_day(PAXG, tf, d))
            d += timedelta(days=1)
        parts = [x for x in parts if len(x)]
        if parts:
            CS.save_bars(MD, PAXG, tf, pd.concat(parts))
    print("paxg archive errors:", len(arc.errors), arc.errors[-3:])


def paxg_feasibility(hs) -> dict:
    """Stage 1 (descriptive only, no predictive test): data coverage, liquidity, spread estimates, a live order-book
    snapshot for slippage, and the PAXG-vs-XAU premium. Predictive questions wait for their own pre-registration."""
    import numpy as np
    from goldquant import crypto_store as CS
    paxg_download()
    h1 = CS.load_bars(MD, PAXG, "1h")
    out = {"schema": 1, "stage": "feasibility (descriptive)", "updated_at": datetime.now(timezone.utc).isoformat()}
    if h1 is None or len(h1) < 1000:
        out["reason"] = "no PAXG history"
        (MODELS / "paxg_feasibility.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        return out
    h1 = h1.astype(float)
    full = pd.date_range(h1.index[0], h1.index[-1], freq="h")
    qv = h1["volume"] * h1["close"]
    out["coverage"] = {"first_bar": str(h1.index[0]), "last_bar": str(h1.index[-1]), "bars": int(len(h1)),
                       "missing_hours_pct": round(100 * (1 - len(h1) / len(full)), 3)}
    yr = h1.index.year
    out["liquidity_by_year"] = {str(y): {
        "median_daily_quote_volume_usd": round(float(qv[yr == y].resample("D").sum().median()), 0),
        "median_hourly_quote_volume_usd": round(float(qv[yr == y].median()), 0),
        "zero_volume_hours_pct": round(100 * float((h1["volume"][yr == y] <= 0).mean()), 2)} for y in sorted(set(yr))}
    last90 = h1[h1.index >= h1.index[-1] - pd.Timedelta(days=90)]
    q90 = last90["volume"] * last90["close"]
    out["liquidity_last_90_days"] = {"median_daily_quote_volume_usd": round(float(q90.resample("D").sum().median()), 0),
                                     "median_hourly_quote_volume_usd": round(float(q90.median()), 0),
                                     "p10_hourly_quote_volume_usd": round(float(q90.quantile(0.1)), 0)}

    def abdi_ranaldo(d: pd.DataFrame) -> float:
        """Close-high-low effective spread estimator (Abdi & Ranaldo 2017), in percent of price."""
        c, eta = np.log(d["close"]), (np.log(d["high"]) + np.log(d["low"])) / 2
        v = 4 * ((c - eta) * (c - eta.shift(-1))).mean()
        return round(100 * float(np.sqrt(max(v, 0.0))), 4)
    out["spread_estimate_pct_by_year"] = {str(y): abdi_ranaldo(h1[yr == y]) for y in sorted(set(yr))}
    out["spread_estimate_pct_last_90_days"] = abdi_ranaldo(last90)
    # live order book snapshot (one moment only): spread and the cost of crossing for given order sizes
    try:
        from goldquant.providers.http import HttpClient
        book = json.loads(HttpClient().get("https://data-api.binance.vision/api/v3/depth", {"symbol": PAXG, "limit": 100}).text)
        bids = [(float(p), float(q)) for p, q in book["bids"]]
        asks = [(float(p), float(q)) for p, q in book["asks"]]
        mid = (bids[0][0] + asks[0][0]) / 2

        def cross(levels, usd):
            left, cost = usd, 0.0
            for p, q in levels:
                take = min(left, p * q)
                cost += take * abs(p / mid - 1)
                left -= take
                if left <= 0:
                    return round(100 * cost / usd, 4)
            return None  # deeper than the 100 visible levels
        out["order_book_snapshot"] = {
            "at": datetime.now(timezone.utc).isoformat(), "mid": mid,
            "spread_pct": round(100 * (asks[0][0] - bids[0][0]) / mid, 4),
            "buy_cost_pct": {str(u): cross(asks, u) for u in (1_000, 10_000, 100_000)},
            "sell_cost_pct": {str(u): cross(bids, u) for u in (1_000, 10_000, 100_000)},
            "depth_usd_within_0.1pct": round(sum(p * q for p, q in bids + asks if abs(p / mid - 1) <= 0.001), 0),
            "note": "one snapshot; costs are half-spread plus walking the book, before the 0.1 % taker fee"}
    except Exception as exc:  # noqa: BLE001
        out["order_book_snapshot"] = {"error": str(exc)[:150]}
    out["fees_assumed"] = {"binance_spot_taker_pct": 0.1, "note": "standard tier; BNB / VIP discounts not assumed"}
    # premium vs spot gold on the hours both trade (XAU = Dukascopy H1 close, same bar open time)
    xau = hs.load_bars("Dukascopy", "XAUUSD", "H1", limit=10_000_000)
    j = pd.concat([h1["close"].rename("paxg"), xau["close"].astype(float).rename("xau")], axis=1, join="inner").dropna()
    prem = 100 * (j["paxg"] / j["xau"] - 1)
    py = prem.index.year
    out["premium_pct_vs_xau"] = {
        "hours_compared": int(len(prem)), "first": str(prem.index[0]) if len(prem) else None,
        "by_year": {str(y): {"n": int((py == y).sum()), "mean": round(float(prem[py == y].mean()), 4),
                             "median": round(float(prem[py == y].median()), 4), "std": round(float(prem[py == y].std()), 4),
                             "p5": round(float(prem[py == y].quantile(0.05)), 4),
                             "p95": round(float(prem[py == y].quantile(0.95)), 4)} for y in sorted(set(py))},
        "note": "PAXG is quoted in USDT and XAU in USD, so the premium also contains the USDT/USD deviation"}
    # weekends available for a later (pre-registered) weekend-gap study: counted only, not analysed here
    fri = xau.index[(xau.index.dayofweek == 4)]
    out["weekends_with_both_series"] = int(len(set(fri.normalize()) & set(h1.index.normalize())))
    (MODELS / "paxg_feasibility.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("coverage", "liquidity_last_90_days", "spread_estimate_pct_last_90_days")}, default=str))
    return out


def paxg_study(hs) -> dict:
    """PAXG stage 2 (goldquant/paxg_study.py, pre-registered): A range engine on PAXG alone, B premium signal after
    costs, C weekend gap. Each test separately; nothing here reaches the app."""
    from goldquant import crypto_store as CS, paxg_study as PS, price_range as PR
    paxg_download(15)
    p = CS.load_bars(MD, PAXG, "1h").astype(float)
    x = hs.load_bars("Dukascopy", "XAUUSD", "H1", limit=10_000_000)
    out = {"schema": 1, "version": PS.VERSION, "updated_at": datetime.now(timezone.utc).isoformat(),
           "A_range": PR.evaluate_asset(p, "crypto"), "B_premium": PS.premium_test(p, x), "C_weekend": PS.weekend_test(p, x)}
    (MODELS / "paxg_study.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for h, r in out["A_range"].items():
        print("A", h, r.get("reason"), (r.get("holdout") or {}).get("m"), flush=True)
    print("B", out["B_premium"].get("reason"), out["B_premium"].get("development"), flush=True)
    print("C", out["C_weekend"].get("reason"), out["C_weekend"].get("walk_forward"), flush=True)
    return out


def hilo_research(hs) -> dict:
    """High / low bounds engine (goldquant/hilo.py, pre-registered): each asset and horizon separately. Research only."""
    from goldquant import crypto_store as CS, hilo as HL
    out = {"schema": 1, "version": HL.VERSION, "updated_at": datetime.now(timezone.utc).isoformat(), "assets": {}}
    frames = {"XAU": ("gold", hs.load_bars("Dukascopy", "XAUUSD", "H1", limit=10_000_000))}
    for sym, a in (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH"), ("SOLUSDT", "SOL")):
        frames[a] = ("crypto", CS.load_bars(MD, sym, "1h"))
    for a, (kind, h1) in frames.items():
        if h1 is None or len(h1) < 8000:
            out["assets"][a] = {"reason": "not enough hourly bars"}
            continue
        out["assets"][a] = HL.evaluate_asset(h1.astype(float), kind)
        for h, r in out["assets"][a].items():
            print(a, h, r.get("reason"), r.get("diff_ci99"), (r.get("holdout") or {}).get("m"), flush=True)
    (MODELS / "hilo_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return out


def activity_models() -> dict:
    """Weekly: re-validate the scalper activity forecast per coin (pre-registered rules in goldquant/activity.py) and
    export the model ONLY for coins that pass this week. A coin that stops passing disappears from the app."""
    from goldquant import activity as ACT, crypto_store as CS
    out = {"schema": 1, "updated_at": datetime.now(timezone.utc).isoformat(), "assets": {}}
    summary = {}
    for sym, a in (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH"), ("SOLUSDT", "SOL")):
        d = CS.load_bars(MD, sym, "15m")
        if len(d) < 20000:
            continue
        r = ACT.evaluate(d)
        out["assets"][a] = {"report": r, "model": ACT.export(d, r) if r["qualified"] else None}
        summary[a] = {k: r.get(k) for k in ("skill", "skill_ci99", "holdout_skill", "qualified", "reason")}
        try:  # challenger: HAR replaces the current model only if it wins out of sample (it never does by itself)
            out["assets"][a]["har_vs_current"] = ACT.compare_har(d)
        except Exception as exc:  # noqa: BLE001
            print(a, "HAR comparison failed:", exc, flush=True)
        print(a, "activity", summary[a], flush=True)
    (MODELS / "activity_models.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                 encoding="utf-8")
    return summary


def data_quality_report(hs: HistoryStore) -> dict:
    """Full-history + last-7-days quality of every stored series -> models/data_quality.json (app + weekly report)."""
    from goldquant import data_quality as DQ
    from goldquant.providers.base import closed_bars
    now = datetime.now(timezone.utc)
    td = {tf: closed_bars(hs.load_bars("TwelveData", "XAU/USD", tf), tf, now) for tf in ("M15", "H1")}
    out = {"generated_at": now.isoformat(), "series": {}}
    for sym in DUKA:
        for tf in ("M15", "H1"):
            b = hs.load_bars("Dukascopy", sym, tf, limit=10_000_000)
            if not len(b):
                continue
            other = td[tf] if sym == "XAUUSD" else None
            out["series"][f"Dukascopy:{sym}:{tf}"] = {"history": DQ.check_bars(b, tf, now, None, other=other),
                                                      "last_7_days": DQ.check_bars(b, tf, now, 7.0, other=other)}
    for tf, b in td.items():
        if len(b):
            out["series"][f"TwelveData:XAU/USD:{tf}"] = {"last_7_days": DQ.check_bars(b, tf, now, 7.0)}
    (MODELS / "data_quality.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("data quality:", {k: (v.get("history") or v["last_7_days"])["status"] for k, v in out["series"].items()})
    return out


def train(hs: HistoryStore) -> None:
    from goldquant.engine import PathService
    try:
        data_quality_report(hs)
    except Exception as exc:  # noqa: BLE001 — reporting must not stop training
        print("data quality report failed:", exc)
    bars, label = training_bars(hs)
    if len(bars["M15"]) < 4000:
        print("not enough history to train:", len(bars["M15"]))
        return
    as_of = (bars["M15"].index[-1] + pd.Timedelta(minutes=15)).to_pydatetime()
    st = PathService().get(type("P", (), {"meta": type("M", (), {"name": label})()})(), as_of, bars)
    cutoff = pd.Timestamp(as_of) - pd.Timedelta(days=90)  # keep artifacts small: recent rows for analogs
    if st.ds is not None:
        st.ds = st.ds[st.ds["decision_time"] >= cutoff]
    if st.fwd is not None:
        st.fwd = st.fwd[st.fwd.index >= cutoff]
    rep = st.models.reports.get(240) if st.models else None
    cloud.save_path_state(st, MODELS, {"trained_at": datetime.now(timezone.utc).isoformat(), "dataset": label,
                                       "trained_until": as_of.isoformat(), "qualified": st.qualified,
                                       "reason": st.reason_ar, "n_oos": getattr(rep, "n_oos", 0)})
    from goldquant.levels import LevelService
    import pickle
    lm = LevelService().model(label, bars, as_of)
    (MODELS / "levels_model.pkl").write_bytes(pickle.dumps(lm))
    print("trained:", label, as_of, "qualified:", st.qualified, st.reason_ar, "levels:", lm.validation.get("reason_ar"))
    try:
        scenario_history(hs)
    except Exception as exc:  # noqa: BLE001
        print("scenario history failed:", exc, flush=True)


def outlook_report(daily: pd.DataFrame, label: str) -> dict:
    """Historical validation of the fixed WEEK / MONTH rules (same function the live engine uses)."""
    import dataclasses
    from goldquant import outlook as OL
    if len(daily) < OL.MIN_DAILY_BARS:
        return {"dataset": label, "status": "INSUFFICIENT", "daily_bars": len(daily)}
    as_of = (daily.index[-1] + pd.Timedelta(days=1)).to_pydatetime()
    views = OL.compute(daily, as_of)
    return {"dataset": label, "daily_bars": len(daily), "from": str(daily.index[0].date()),
            "to": str(daily.index[-1].date()), "cost_round_trip": OL.ROUND_TRIP_COST,
            "rules": {v.horizon: {"rule_ar": OL.RULE_AR[v.horizon], "validated": v.validated,
                                  "current_action": v.action, "current_tilt": v.tilt,
                                  "stats": dataclasses.asdict(v.stats)} for v in views},
            "note_ar": "القواعد ثابتة مسبقاً (بلا بحث عن معاملات)؛ النسبة تكرار تاريخي غير متداخل بعد التكاليف"}


def planner_macro(hs: HistoryStore) -> dict:
    """FRED series for the planner, extended back to 2006 once (fredgraph.csv, no key) so the A/B covers the same
    long period as the daily bars. Point in time: rows carry a conservative published_at (sources/fred.py)."""
    from goldquant import planner as PLN
    from goldquant.sources.fred import FredSource
    far = datetime(2100, 1, 1, tzinfo=timezone.utc)
    out, extended = {}, False
    for s_ in PLN.MACRO_SERIES:
        df = hs.load_observations_as_of("FRED", s_, far)
        if df.empty or str(df["observed_at"].iloc[0]) > "2008":
            try:
                hs.upsert_observations("FRED", s_, FredSource().fetch(s_, start="2006-01-01"))
                df = hs.load_observations_as_of("FRED", s_, far)
                extended = True
            except Exception as exc:  # noqa: BLE001
                print("FRED history", s_, "failed:", exc)
        out[s_] = df
    if extended:
        for s_ in MACRO_SERIES:
            cloud.export_observations(hs, MD, "FRED", s_)
        print("FRED history from", {k: str(v["observed_at"].iloc[0])[:10] for k, v in out.items() if len(v)})
    return out


def _macro_since(macro: dict):
    firsts = [str(v["observed_at"].iloc[0])[:10] for v in macro.values() if len(v)]
    if len(firsts) < 3:
        return None
    y, m, d_ = max(firsts).split("-")
    return f"{int(y) + 1}-{m}-{d_}"  # one year of warm-up for 20-obs changes and the 252-obs GVZ z-score


def research(hs: HistoryStore) -> None:
    try:  # weekly re-validation of the touch-probability engine: a failing asset-horizon disappears from the app
        MODELS.mkdir(parents=True, exist_ok=True)
        touch_models(hs)
    except Exception as exc:  # noqa: BLE001 — never block the rest of the weekly research
        print("touch re-validation failed:", exc, flush=True)
    try:  # weekly re-validation of the price-range engine (same pre-registered rules; nothing is re-tuned)
        range_research(hs)
    except Exception as exc:  # noqa: BLE001
        print("range re-validation failed:", exc, flush=True)
    from goldquant import setups
    from goldquant.precision import promotion as PR
    from goldquant.precision.feature_upgrade import compare
    from goldquant.precision.report import full_report
    bars, label = training_bars(hs)
    if len(bars["M15"]) < 4000:
        print("not enough history for research")
        return
    MODELS.mkdir(parents=True, exist_ok=True)
    rep = full_report(bars["M15"], bars["H1"], bars["H4"], label)
    (MODELS / "precision_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    PR.save(MODELS / "promotions.json", rep.get("promotion", []), label)
    prov = "Dukascopy" if "Dukascopy" in label else "TwelveData"
    from goldquant.features_ext import CROSS_ASSETS
    aux = {s: hs.load_bars(prov, s, "M15") for s in CROSS_ASSETS}
    aux = {k: v for k, v in aux.items() if len(v) > 1000}
    fu = compare(bars["M15"], bars["H1"], bars["H4"], aux or None, dataset_label=label)
    (MODELS / "feature_upgrade.json").write_text(json.dumps(fu, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    su = setups.evaluate(bars["M15"], bars["H1"], bars["H4"])
    (MODELS / "setups.json").write_text(json.dumps(su, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    try:  # out-of-sample walk-forward backtest of the HOURS rule (costs, realistic execution) for the app
        from goldquant import backtest as BT
        from goldquant.reliability.execution import ExecutionModel
        bt = BT.run(bars["M15"], bars["H1"], bars["H4"], final=False, execution=ExecutionModel())
        bt.pop("trade_pnls", None)
        bt["dataset"] = label
        (MODELS / "backtest_report.json").write_text(json.dumps(bt, ensure_ascii=False, indent=1, default=str),
                                                     encoding="utf-8")
        print("backtest:", {k: bt.get(k) for k in ("trades", "win_rate", "ev_per_trade", "max_drawdown")})
    except Exception as exc:  # noqa: BLE001
        print("backtest failed:", exc)
    daily = hs.load_bars("TwelveData", "XAU/USD", "D1", limit=10_000)
    macro = planner_macro(hs)
    try:  # trade-plan engine for WEEK / MONTH: walk-forward report + production model (used only if qualified)
        import pickle
        from dataclasses import asdict
        from goldquant import planner as PLN
        reps, cmp_ = {}, {}
        since = _macro_since(macro)
        for hz in PLN.DAILY_HZ:
            r = PLN.walk_forward(daily, hz)
            chosen, chosen_macro = r, None
            if since is not None:  # same period, with vs without FRED macro features (honest A/B, both reported)
                rb = PLN.walk_forward(daily, hz, since=since)
                rm = PLN.walk_forward(daily, hz, macro=macro, cols=PLN.FEATURES + PLN.MACRO, since=since)
                cmp_[hz] = {"since": since, "base": asdict(rb), "macro": asdict(rm)}
                print("planner", hz, "A/B since", since, "| base", rb.expectancy_pct, rb.direction_accuracy, rb.reason,
                      "| macro", rm.expectancy_pct, rm.direction_accuracy, rm.reason)
                if rm.qualified and not r.qualified:
                    chosen, chosen_macro = rm, macro  # macro variant is used only if IT qualified on its own
            regs = {}
            for rg in PLN.REGIMES:  # pre-registered regimes; a regime model must qualify on its own (>= 30 holdout trades)
                rr = PLN.walk_forward(daily, hz, regime=rg)
                regs[rg] = asdict(rr)
                print("planner", hz, "regime", rg, rr.trades, rr.expectancy_pct, rr.reason)
                if not chosen.qualified and rr.qualified and rr.holdout_trades >= 30:
                    chosen, chosen_macro = rr, None
            cmp_.setdefault("regimes", {})[hz] = regs
            reps[hz] = asdict(chosen)
            (MODELS / f"planner_{hz}.pkl").write_bytes(pickle.dumps(PLN.train_production(daily, hz, chosen, chosen_macro)))
            print("planner", hz, chosen.reason, {k: reps[hz][k] for k in ("trades", "expectancy_pct", "baseline_expectancy_pct")})
        h1 = hs.load_bars("Dukascopy", "XAUUSD", "H1", limit=200_000)
        if len(h1) > 4000:  # HOURS plan engine on H1 bars: reported (app performance block), not used for trades
            rh = PLN.walk_forward(h1, "HOURS", cols=PLN.FEATURES + PLN.INTRADAY)
            reps["HOURS"] = asdict(rh)
            cmp_.setdefault("regimes", {})["HOURS"] = {
                rg: asdict(PLN.walk_forward(h1, "HOURS", cols=PLN.FEATURES + PLN.INTRADAY, regime=rg)) for rg in PLN.REGIMES}
            aux = {s_: hs.load_bars("Dukascopy", s_, "H1", limit=200_000) for s_ in PLN.CROSS_SYMBOLS}
            aux = {k: v for k, v in aux.items() if len(v) > 15000}  # >= ~3 years, so the A/B covers a long period
            if len(aux) >= 3:  # same period, with vs without intraday cross-asset returns (both reported)
                since = str(max(v.index[0] for v in aux.values()) + pd.Timedelta(days=30))[:10]
                cb = PLN.walk_forward(h1, "HOURS", cols=PLN.FEATURES + PLN.INTRADAY, since=since)
                cx = PLN.walk_forward(h1, "HOURS", cols=PLN.FEATURES + PLN.INTRADAY + PLN.cross_cols(aux),
                                      since=since, aux=aux)
                cmp_["HOURS_cross"] = {"since": since, "assets": sorted(aux), "base": asdict(cb), "cross": asdict(cx)}
                print("planner HOURS A/B since", since, sorted(aux), "| base", cb.expectancy_pct, cb.direction_accuracy,
                      cb.reason, "| cross", cx.expectancy_pct, cx.direction_accuracy, cx.reason)
            print("planner HOURS", rh.reason, {k: reps["HOURS"][k] for k in ("trades", "expectancy_pct", "baseline_expectancy_pct")})
        (MODELS / "planner_report.json").write_text(json.dumps(reps, ensure_ascii=False, indent=1, default=str),
                                                    encoding="utf-8")
        (MODELS / "planner_macro_ab.json").write_text(json.dumps(cmp_, ensure_ascii=False, indent=1, default=str),
                                                      encoding="utf-8")
        from goldquant import scalp as SC
        from goldquant.providers.base import market_closed_mask
        import numpy as np
        m15 = hs.load_bars("Dukascopy", "XAUUSD", "M15", limit=10_000_000)
        if len(m15) > 20000:  # scalping lab on gold: no trade whose 4-hour window reaches the weekly close
            trad = ~np.asarray(market_closed_mask(m15.index)) & ~np.asarray(market_closed_mask(m15.index + pd.Timedelta(hours=4.5)))
            (MODELS / "scalp_report.json").write_text(json.dumps(
                {"XAUUSD": {"cost": 0.0003, "results": SC.run_all(m15, 0.0003, trad) + SC.run_all(
                    m15, 0.0003, trad, rules=SC.GOLD_RULES2, ci_level=SC.CI_ROUND2)}}, ensure_ascii=False, indent=1,
                default=str), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print("planner failed:", exc)
    (MODELS / "outlook_report.json").write_text(json.dumps(outlook_report(daily, "TwelveData D1"), ensure_ascii=False,
                                                           indent=1, default=str), encoding="utf-8")
    print("research written")
    try:  # weekly re-validation of the multi-asset tournament
        pooled_research(hs)
    except Exception as exc:  # noqa: BLE001
        print("pooled research failed:", exc, flush=True)


def report(hs: HistoryStore) -> None:
    """Weekly plain-language status: data coverage, model state, live forward record (no new numbers invented)."""
    rd = ROOT / "reports"
    rd.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    L = [f"# GOLD AI QUANT — weekly report {now:%Y-%m-%d}", ""]
    L.append("## Data coverage")
    for prov, sym in (("Dukascopy", "XAUUSD"), ("TwelveData", "XAU/USD")):
        for tf in ("M15", "D1"):
            b = hs.load_bars(prov, sym, tf, limit=10_000_000)
            if len(b):
                L.append(f"- {prov} {sym} {tf}: {len(b):,} bars, {b.index[0]:%Y-%m-%d} → {b.index[-1]:%Y-%m-%d %H:%M} UTC")
    def jload(name):
        p = MODELS / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    m = jload("manifest.json") or {}
    L += ["", "## Intraday model (HOURS)",
          f"- trained: {m.get('trained_at', '—')} on {m.get('dataset', '—')}",
          f"- qualified for BUY/SELL: {'YES' if m.get('qualified') else 'NO'} — {m.get('reason', '')}",
          f"- out-of-sample decisions evaluated: {m.get('n_oos', 0)}"]
    t = (jload("outlook_track.json") or {}).get("horizons", {})
    L += ["", "## Live forward record (WEEK / MONTH, after costs)"]
    for hz in ("WEEK", "MONTH"):
        h = t.get(hz) or {}
        n, k = h.get("resolved", 0), h.get("hits", 0)
        rate = f"{k / n:.0%}" if n else "—"
        L.append(f"- {hz}: {k}/{n} correct ({rate}), {h.get('pending', 0)} pending"
                 + (" — fewer than 30 results: not meaningful yet" if n < 30 else ""))
    o = jload("outlook_report.json") or {}
    if o:
        L += ["", "## WEEK / MONTH rule validation (historical, non-overlapping)"]
        for hz, v in (o.get("horizons") or {}).items():
            if isinstance(v, dict):
                L.append(f"- {hz}: validated={v.get('validated')} hit_rate={v.get('hit_rate')} n={v.get('n')}")
    log = MODELS / "td_usage.jsonl"
    if log.exists():
        recs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
        recs = [r for r in recs if isinstance(r.get("daily_usage"), (int, float))]
        if recs:
            peak = max(recs, key=lambda r: r["daily_usage"])
            lim = peak.get("plan_daily_limit") or 0
            L += ["", "## Twelve Data credits (free plan)",
                  f"- highest daily use seen this week: {peak['daily_usage']} of {lim or '?'}"
                  + (" — WARNING: above 80 %, raise GOLDQUANT_LIVE_TTL_S on Render" if lim and peak["daily_usage"] > 0.8 * lim else "")]
    L += ["", "_Frequencies, not probabilities. Paper trading and research only._"]
    (rd / "weekly.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)  # show progress live in the Actions log
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "train", "research", "backfill", "report", "crypto", "crypto_research",
                                    "crypto_weekly", "scalp1m", "pooled", "scalp_feasibility", "scalp_ml", "scalp_book",
                                    "touch", "range", "paxg", "paxg_study", "hilo"])
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--first", type=date.fromisoformat, default=None, help="backfill range start (YYYY-MM-DD)")
    ap.add_argument("--last", type=date.fromisoformat, default=None, help="backfill range end (YYYY-MM-DD)")
    ap.add_argument("--budget-min", type=float, default=None)
    ap.add_argument("--symbols", default="", help="comma-separated Dukascopy symbols (backfill); default: all")
    a = ap.parse_args()
    if a.cmd in ("scalp1m", "scalp_feasibility", "scalp_ml", "scalp_book"):
        MODELS.mkdir(parents=True, exist_ok=True)
        {"scalp1m": scalp1m, "scalp_feasibility": scalp_feasibility, "scalp_ml": scalp_ml,
         "scalp_book": scalp_book}[a.cmd](a.budget_min or 75)
        raise SystemExit(0)
    if a.cmd.startswith("crypto"):  # crypto lives in its own files; no HistoryStore import needed
        MODELS.mkdir(parents=True, exist_ok=True)
        if a.cmd in ("crypto", "crypto_weekly"):
            crypto(a.budget_min)
        if a.cmd in ("crypto_research", "crypto_weekly"):
            crypto_research()
        raise SystemExit(0)
    hs = load()
    if a.cmd == "collect":
        collect(hs)
        save(hs)
    elif a.cmd == "backfill":
        backfill(hs, a.years, a.first, a.last, a.budget_min, tuple(x for x in a.symbols.split(",") if x) or None)
        save(hs)
    elif a.cmd == "train":
        train(hs)
    elif a.cmd == "report":
        report(hs)
    elif a.cmd == "touch":
        MODELS.mkdir(parents=True, exist_ok=True)
        touch_models(hs)
    elif a.cmd == "hilo":
        MODELS.mkdir(parents=True, exist_ok=True)
        hilo_research(hs)
    elif a.cmd == "paxg_study":
        MODELS.mkdir(parents=True, exist_ok=True)
        paxg_study(hs)
    elif a.cmd == "paxg":
        MODELS.mkdir(parents=True, exist_ok=True)
        paxg_feasibility(hs)
    elif a.cmd == "range":
        MODELS.mkdir(parents=True, exist_ok=True)
        range_research(hs)
    elif a.cmd == "pooled":
        MODELS.mkdir(parents=True, exist_ok=True)
        pooled_research(hs)
    else:
        research(hs)
