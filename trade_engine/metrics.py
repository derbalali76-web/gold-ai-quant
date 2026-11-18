"""Trade metrics with honest uncertainty: Wilson intervals for rates, bootstrap intervals for mean and PF."""
from __future__ import annotations
import math
import numpy as np


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(c - h, 4), round(c + h, 4)


def pf(x: np.ndarray) -> float | None:
    loss = -x[x < 0].sum()
    return None if loss == 0 else float(x[x > 0].sum() / loss)


def boot(x: np.ndarray, fn, n: int = 2000, seed: int = 7, block: int = 5) -> tuple[float, float] | None:
    """Moving-block bootstrap (trades are in time order and neighbours are not independent)."""
    if len(x) < 10:
        return None
    rng = np.random.default_rng(seed)
    nb = math.ceil(len(x) / block)
    vals = []
    for _ in range(n):
        st = rng.integers(0, len(x) - block + 1, nb)
        s = np.concatenate([x[i:i + block] for i in st])[:len(x)]
        v = fn(s)
        if v is not None and np.isfinite(v):
            vals.append(v)
    if not vals:
        return None
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return round(float(lo), 6), round(float(hi), 6)


def max_dd(net: np.ndarray) -> float:
    eq = np.cumprod(1 + net)
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    return float((1 - eq / peak).max()) if len(eq) else 0.0


def summary(results) -> dict:
    rows = [r for r in results if r.outcome != "NO_DATA"]
    filled = [r for r in rows if r.filled]
    net = np.array([r.net for r in filled])
    tgt = sum(r.outcome == "TARGET" for r in filled)
    stp = sum(r.outcome == "STOP" for r in filled)
    win = int((net > 0).sum())
    return {
        "orders": len(rows), "filled": len(filled),
        "fill_rate": round(len(filled) / len(rows), 4) if rows else None, "fill_rate_ci": wilson(len(filled), len(rows)),
        "p_target_first": round(tgt / len(filled), 4) if filled else None, "p_target_first_ci": wilson(tgt, len(filled)),
        "stops": stp, "time_exits": len(filled) - tgt - stp,
        "p_net_win": round(win / len(filled), 4) if filled else None, "p_net_win_ci": wilson(win, len(filled)),
        "mean_net_pct": round(100 * net.mean(), 4) if len(net) else None,
        "mean_net_ci_pct": (lambda c: c and (round(100 * c[0], 4), round(100 * c[1], 4)))(boot(net, np.mean)),
        "profit_factor": round(pf(net), 3) if len(net) and pf(net) else None,
        "profit_factor_ci": boot(net, pf),
        "total_return_pct": round(100 * (np.prod(1 + net) - 1), 2) if len(net) else 0.0,
        "max_drawdown_pct": round(100 * max_dd(net), 2) if len(net) else 0.0,
        "avg_bars_held": round(float(np.mean([r.bars_held for r in filled])), 1) if filled else None,
    }


def month_block_boot(months: np.ndarray, x: np.ndarray, fn, n: int = 2000, block: int = 3, seed: int = 7):
    """Circular block bootstrap over calendar months (addendum A1-2). months: 'YYYY-MM' per trade (time order)."""
    if len(x) < 10:
        return None
    keys = sorted(set(months))
    groups = [x[months == k] for k in keys]
    nm = len(keys)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        parts, got = [], 0
        while got < nm:
            s = int(rng.integers(0, nm))
            for d in range(block):
                parts.append(groups[(s + d) % nm])
            got += block
        v = fn(np.concatenate(parts)) if parts else None
        if v is not None and np.isfinite(v):
            vals.append(v)
    if not vals:
        return None
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return round(float(lo), 6), round(float(hi), 6)


def brier_skill(p: np.ndarray, base: np.ndarray, y: np.ndarray):
    if len(y) == 0:
        return None
    den = float(((base - y) ** 2).sum())
    return None if den == 0 else round(1 - float(((p - y) ** 2).sum()) / den, 4)


def reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list:
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        sel = (p >= lo) & ((p < hi) if i < bins - 1 else (p <= hi))
        if sel.any():
            out.append({"bin": [lo, hi], "n": int(sel.sum()), "mean_p": round(float(p[sel].mean()), 4),
                        "observed": round(float(y[sel].mean()), 4)})
    return out
