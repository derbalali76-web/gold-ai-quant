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
DUKA = ("XAUUSD", "XAGUSD", "EURUSD", "USDJPY")
AUX_TD = {"EUR/USD": "EURUSD", "USD/JPY": "USDJPY", "XAG/USD": "XAGUSD"}
TFS = {"M15": 15, "H1": 60, "H4": 240}


def load() -> HistoryStore:
    hs = HistoryStore()
    print("loaded:", cloud.import_tree(hs, MD))
    return hs


def save(hs: HistoryStore) -> None:
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
        for tf in TFS:
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
    imp = DukascopyImporter()
    for sym in DUKA:  # yesterday + today-so-far (closed minutes only)
        try:
            m1 = imp.fetch_range(sym, (now - timedelta(days=1)).date(), (now - timedelta(days=1)).date())
            store_duka(hs, sym, m1)
        except Exception as exc:  # noqa: BLE001
            print("Duka", sym, exc)
    ctx = ContextService(hs, ROOT / "config" / "calendar.json")
    ctx.refresh(now)
    for r in hs.recent_fetches(40):
        print(r)


def backfill(hs: HistoryStore, years: float) -> None:
    imp = DukascopyImporter()
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=int(365 * years))
    for sym in DUKA:
        d = start
        while d <= end:
            chunk_end = min(end, d + timedelta(days=30))
            m1 = imp.fetch_range(sym, d, chunk_end)
            store_duka(hs, sym, m1)
            print(sym, d, chunk_end, len(m1), "errors:", len(imp.errors))
            d = chunk_end + timedelta(days=1)


def training_bars(hs: HistoryStore):
    """One consistent feed for training: Dukascopy if long and current, else Twelve Data."""
    duka = {tf: hs.load_bars("Dukascopy", "XAUUSD", tf) for tf in TFS}
    td = {tf: hs.load_bars("TwelveData", "XAU/USD", tf) for tf in TFS}
    fresh = lambda b: len(b["M15"]) and (pd.Timestamp.now(tz="UTC") - b["M15"].index[-1]) < pd.Timedelta(days=4)  # noqa
    if len(duka["M15"]) >= 4000 and fresh(duka) and len(duka["M15"]) >= len(td["M15"]):
        return duka, "LIVE HISTORY (Dukascopy)"
    return td, "LIVE HISTORY (TwelveData)"


def train(hs: HistoryStore) -> None:
    from goldquant.engine import PathService
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


def research(hs: HistoryStore) -> None:
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
    aux = {s: hs.load_bars(prov, s, "M15") for s in ("XAGUSD", "EURUSD", "USDJPY")}
    aux = {k: v for k, v in aux.items() if len(v) > 1000}
    fu = compare(bars["M15"], bars["H1"], bars["H4"], aux or None, dataset_label=label)
    (MODELS / "feature_upgrade.json").write_text(json.dumps(fu, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    su = setups.evaluate(bars["M15"], bars["H1"], bars["H4"])
    (MODELS / "setups.json").write_text(json.dumps(su, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("research written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "train", "research", "backfill"])
    ap.add_argument("--years", type=float, default=3.0)
    a = ap.parse_args()
    hs = load()
    if a.cmd == "collect":
        collect(hs)
        save(hs)
    elif a.cmd == "backfill":
        backfill(hs, a.years)
        save(hs)
    elif a.cmd == "train":
        train(hs)
    else:
        research(hs)
