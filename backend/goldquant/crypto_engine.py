"""Crypto analysis (BTC / ETH / SOL): the same honest screen as gold — trend, levels, today's scenarios, entry
checklist, data health — built from Binance's public market data (real volume), 24/7.

No recommendation is issued: every horizon stays WAIT until that coin's own walk-forward research qualifies
(models/crypto_report.json). Gold's models, levels and costs are never reused for a coin.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from . import brief as BR
from . import checklist as CK
from . import data_quality as DQ
from . import outlook as OL
from . import plans as PL
from .features import frame_features
from .levels import LevelService, compute_levels
from .msg import M as Mg
from .providers.http import HttpClient, HttpError, RateLimiter
from .schemas import (Action, DataFreshness, DataHealth, Decision, DQCheck, HorizonOutlook, LevelsBlock, MarketTrend,
                      Mode, PriceLevel, SpotOrProxy)
from .trend import market_trend
from .engine import _ref

VERSION = "crypto-analysis-1.0.0"
ASSETS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
LIVE = "https://data-api.binance.vision/api/v3/klines"  # public market-data mirror (reachable from US servers)
TFS = {"M15": "15m", "M30": "30m", "H1": "1h", "H4": "4h"}
TTL_S = 120


def parse_klines(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "qv", "n",
                                     "tbv", "tbqv", "x"])
    out = pd.DataFrame({k: pd.to_numeric(df[k]) for k in ("open", "high", "low", "close", "volume")})
    out["tick_volume"] = out["volume"]
    out["taker_buy_volume"] = pd.to_numeric(df["tbv"])
    out.index = pd.to_datetime(pd.to_numeric(df["open_time"]), unit="ms", utc=True)
    out.index.name = "open_time"
    return out


class CryptoFeed:
    """Closed bars from the public mirror, cached a couple of minutes per (symbol, timeframe)."""

    def __init__(self, http: Optional[HttpClient] = None):
        self.http = http or HttpClient(limiter=RateLimiter(calls=60, period=60.0), retries=2, backoff=1.0, timeout=15.0)
        self._cache: dict = {}
        self._lock = threading.Lock()

    def bars(self, symbol: str, tf: str, as_of: datetime, limit: int = 1000) -> pd.DataFrame:
        key = (symbol, tf)
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < TTL_S:
                df = hit[1]
            else:
                r = self.http.get(LIVE, {"symbol": symbol, "interval": tf if tf in ("1d",) else TFS[tf], "limit": limit})
                df = parse_klines(json.loads(r.text))
                self._cache[key] = (time.time(), df)
        step = pd.Timedelta(minutes={"M15": 15, "M30": 30, "H1": 60, "H4": 240, "1d": 1440}[tf])
        return df[df.index + step <= pd.Timestamp(as_of)]


def _cards(daily: Optional[pd.DataFrame], as_of: datetime) -> list[HorizonOutlook]:
    """WEEK / MONTH context (trend + daily levels) from the coin's own daily bars; never validated here."""
    out = []
    try:
        views = OL.compute(daily, as_of, synthetic=False) if daily is not None and len(daily) > 260 else []
    except Exception:  # noqa: BLE001
        views = []
    for v in views:
        lv = None
        if v.levels:
            lv = LevelsBlock(supports=[PriceLevel(**z) for z in v.levels["supports"]],
                             resistances=[PriceLevel(**z) for z in v.levels["resistances"]], validated=False,
                             method_note_ar=str(v.levels["method_ref"]))
        st = Mg("st.wait_lean_buy" if v.tilt > 0 else "st.wait_lean_sell" if v.tilt < 0 else "st.wait")
        un = Mg("va.crypto_unq")
        out.append(HorizonOutlook(horizon=v.horizon, label_ar=OL.LABEL_AR[v.horizon], action=Action.WAIT, tilt=v.tilt,
                                  stance_ar=str(st), reason_ar=str(un), validated=False, validation_ar=str(un),
                                  stance_ref=_ref(st), reason_ref=_ref(un), validation_ref=_ref(un),
                                  horizon_days=OL.HORIZON_DAYS[v.horizon],
                                  levels=lv, trend=MarketTrend(**v.trend) if v.trend else None))
    return out


def decide(asset: str, feed: CryptoFeed, as_of: Optional[datetime] = None,
           levels: Optional[LevelService] = None) -> Decision:
    sym = ASSETS[asset]
    as_of = as_of or datetime.now(timezone.utc)
    did = hashlib.sha256(f"{sym}|{as_of.isoformat()}".encode()).hexdigest()[:16]
    base = dict(decision_id=did, mode=Mode.LIVE, instrument=f"{asset}/USD", spot_or_proxy=SpotOrProxy.SPOT,
                provider="Binance", analyzed_at_utc=as_of, model_version=VERSION, snapshot_hash=did)
    try:
        bars = {tf: feed.bars(sym, tf, as_of) for tf in TFS}
        daily = feed.bars(sym, "1d", as_of)
    except (HttpError, ValueError, KeyError) as exc:
        msg = Mg("un.no_quote")
        return Decision(action=Action.UNAVAILABLE, data_freshness=DataFreshness(max_allowed_seconds=900, is_fresh=False),
                        data_quality="INSUFFICIENT", warning_ar=str(msg), reason_short_ar=str(msg),
                        warning_ref=_ref(msg), reason_short_ref=_ref(msg),
                        missing_data=[str(exc)[:120]], **base)
    m15 = bars["M15"]
    price = float(m15["close"].iloc[-1])
    q_time = (m15.index[-1] + pd.Timedelta(minutes=15)).to_pydatetime()
    age = (as_of - q_time).total_seconds()
    dq = {}
    for tf in ("M15", "H1"):
        r = DQ.check_bars(bars[tf], tf, as_of, 7.0, market="crypto")
        for c in r["checks"]:
            # crypto trades 24/7 with real exchange volume: big genuine jumps happen (news, liquidations), so an
            # abnormal jump is a warning here, not a block; broken bars / frozen prices / stale data still block
            if c["code"] in ("coverage", "gaps", "outliers") and c["status"] == DQ.FAIL:
                c["status"] = DQ.WARN
            prev = dq.get(c["code"])
            if prev is None or DQ.RANK[c["status"]] > DQ.RANK[prev["status"]]:
                dq[c["code"]] = dict(c, tf=tf)
    dq_status = max((c["status"] for c in dq.values()), key=DQ.RANK.get, default=DQ.WARN)
    health = DataHealth(status=dq_status, checks=[DQCheck(**c) for c in dq.values()])
    fresh = 0 <= age <= 900
    fr = DataFreshness(quote_age_seconds=age, max_allowed_seconds=900, is_fresh=fresh,
                       bars_available={tf: len(b) for tf, b in bars.items()})
    common = dict(quote=round(price, 2), quote_timestamp_utc=q_time, data_freshness=fr, data_health=health, **base)
    if dq_status == DQ.FAIL or not fresh:
        msg = Mg("un.dq_fail", ", ".join(k for k, c in dq.items() if c["status"] == DQ.FAIL)) if dq_status == DQ.FAIL \
            else Mg("un.stale", f"{age:.0f}")
        return Decision(action=Action.UNAVAILABLE, data_quality="INSUFFICIENT", warning_ar=str(msg),
                        reason_short_ar=str(msg), warning_ref=_ref(msg), reason_short_ref=_ref(msg), **common)
    fe = {tf: frame_features(df).iloc[-1] for tf, df in bars.items()}
    trend = MarketTrend(**market_trend(fe, "RANGE"))
    ls = levels or LevelService()
    sr = compute_levels(bars, as_of, price, ls.model(("crypto", sym), bars, as_of))
    lv = LevelsBlock(supports=sr["supports"], resistances=sr["resistances"], validated=False, atr_h1=sr["atr_h1"],
                     method_note_ar=sr["method_note_ar"], validation_ar=str(Mg("va.crypto_unq")))
    hours = HorizonOutlook(horizon="HOURS", label_ar=OL.LABEL_AR["HOURS"], action=Action.WAIT,
                           tilt=1 if trend.direction == "UP" else -1 if trend.direction == "DOWN" else 0,
                           stance_ar=str(Mg("st.wait")), reason_ar=str(Mg("va.crypto_unq")), validated=False,
                           validation_ar=str(Mg("va.crypto_unq")), levels=lv, trend=trend,
                           stance_ref=_ref(Mg("st.wait")), reason_ref=_ref(Mg("va.crypto_unq")),
                           validation_ref=_ref(Mg("va.crypto_unq")))
    msg = Mg("va.crypto_unq")
    d = Decision(action=Action.WAIT, data_quality="GOOD" if dq_status == DQ.OK else "DEGRADED", market_trend=trend,
                 levels=lv, outlooks=[hours] + _cards(daily, as_of), reason_short_ar=str(msg), warning_ar=str(msg),
                 reason_short_ref=_ref(msg), warning_ref=_ref(msg), **common)
    PL.attach(d)
    CK.attach(d, None)
    d.daily_brief = BR.build(d)
    return d
