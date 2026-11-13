"""Setup engine: trade specific, well-defined situations instead of every bar.

  LONDON_BREAKOUT : first M15 close beyond the Asian-session range between 08:00 and 10:00 London time
  SWEEP_RECLAIM   : a sweep of the 20-bar extreme that closes back inside (liquidity-trap inference)
  NY_OPEN_DRIVE   : strong directional move (>= 0.5 ATR) over the two bars ending 08:45 New York (COMEX opens 08:20)

Each setup is evaluated out-of-sample, raw and with the production model's expected-value gate, net of costs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import model as M
from . import path as P
from .features import atr
from .features_ext import LONDON, NEW_YORK
from .intel.liquidity_trap import event_series
from .precision import data as D
from .precision import wf as W

SETUPS = ("LONDON_BREAKOUT", "SWEEP_RECLAIM", "NY_OPEN_DRIVE")


def detect(m15: pd.DataFrame) -> pd.DataFrame:
    """Per bar (indexed by OPEN time like m15): direction of each setup (+1/-1/0). Uses only closed bars."""
    close_t = m15.index + pd.Timedelta(minutes=15)
    lt, nt = close_t.tz_convert(LONDON), close_t.tz_convert(NEW_YORK)
    lmin, nmin = lt.hour * 60 + lt.minute, nt.hour * 60 + nt.minute
    ldate = pd.Index(lt.date)
    out = pd.DataFrame(0, index=m15.index, columns=list(SETUPS), dtype=int)
    # Asian range (London-clock 00:00-07:00) known by 07:00 London
    asia = (lmin > 0) & (lmin <= 7 * 60)
    hi = pd.Series(np.where(asia, m15["high"], np.nan), index=m15.index).groupby(ldate).transform("max")
    lo = pd.Series(np.where(asia, m15["low"], np.nan), index=m15.index).groupby(ldate).transform("min")
    window = (lmin > 8 * 60) & (lmin <= 10 * 60)
    up = window & (m15["close"] > hi)
    dn = window & (m15["close"] < lo)
    sig = pd.Series(np.where(up, 1, np.where(dn, -1, 0)), index=m15.index)
    first = sig.ne(0) & ~sig.ne(0).groupby(ldate).cumsum().gt(1)
    out["LONDON_BREAKOUT"] = np.where(first, sig, 0)
    out["SWEEP_RECLAIM"] = event_series(m15).fillna(0).astype(int).to_numpy()
    a = atr(m15)
    move = m15["close"] - m15["close"].shift(2)
    drive = (nmin == 8 * 60 + 45) & (move.abs() >= 0.5 * a)  # close of the bar ~25 min after the 08:20 open
    out["NY_OPEN_DRIVE"] = np.where(drive, np.sign(move), 0).astype(int)
    return out


def evaluate(m15, h1, h4, n_folds: int = 5, dev_frac: float = 0.8) -> dict:
    table = D.feature_table(m15, h1, h4)
    det = detect(m15)
    det.index = det.index + pd.Timedelta(minutes=15)  # align to decision (close) time like the feature table
    ds = P.build_path_dataset(m15, h1, h4)
    emb = pd.Timedelta(minutes=240)
    res = {}
    for name in SETUPS:
        d = det[name].reindex(table.index).fillna(0).to_numpy()
        out, pnl, known = D.realised(m15, table["atr"].to_numpy(), d.astype(float), 240, 2.0, 1.0)
        rows = table.copy()
        for c in M.DIRECTIONAL:
            rows[c] = rows[c] * d
        rows["dir"], rows["out"], rows["pnl"] = d.astype(float), out, pnl
        rows["known_at"] = pd.to_datetime(known, unit="m", utc=True)
        rows["decision_time"] = rows.index
        rows = rows[(rows["dir"] != 0)].dropna(subset=M.FEATURES + ["pnl"])
        if len(rows) < 30:
            res[name] = {"signals": int(len(rows)), "status": "INSUFFICIENT"}
            continue
        t0, t1 = rows["decision_time"].min(), rows["decision_time"].max()
        cut = t0 + dev_frac * (t1 - t0)
        dev = rows[rows["decision_time"] < cut - emb]
        days = dev["decision_time"].dt.floor("D").to_numpy()
        raw = W.summarize(dev["pnl"].to_numpy(), dev["out"].to_numpy(), days, len(dev))
        # model-gated, walk-forward: primary refit before each block on outcomes known before it
        edges = np.linspace(0.4, 1.0, n_folds + 1)
        acc_pnl, acc_out, acc_days = [], [], []
        for a_, b_ in zip(edges[:-1], edges[1:]):
            s, e = t0 + a_ * (cut - t0), t0 + b_ * (cut - t0)
            blk = dev[(dev["decision_time"] >= s) & (dev["decision_time"] < e)]
            prim, _ = W._fit_primary(ds, s - emb)
            if prim is None or blk.empty:
                continue
            p = W._proba(prim, blk[M.FEATURES].to_numpy())
            ok = W.ev_r(p, 1.0, blk["atr"].to_numpy() * 2.0) >= W.MIN_EDGE_R
            acc_pnl.append(blk["pnl"].to_numpy()[ok]); acc_out.append(blk["out"].to_numpy()[ok])
            acc_days.append(blk["decision_time"].dt.floor("D").to_numpy()[ok])
        gated = W.summarize(np.concatenate(acc_pnl) if acc_pnl else np.array([]),
                            np.concatenate(acc_out) if acc_out else np.array([]),
                            np.concatenate(acc_days) if acc_days else np.array([]), max(1, len(dev)))
        res[name] = {"signals": int(len(rows)), "development_raw": raw, "development_model_gated_oos": gated}
    return {"setups": res, "note_ar": "عائد بعد التكاليف؛ فترة التطوير فقط؛ الحجز النهائي لم يُلمس"}
