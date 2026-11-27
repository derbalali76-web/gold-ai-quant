import gzip, json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import replay as R
SPLIT = pd.Timestamp("2026-06-01T00:00:00Z")

def rsi(c, n=6):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)

rows = pd.DataFrame([json.loads(x) for x in gzip.open(HERE / "samples.jsonl.gz", "rt")])
buys = rows[(rows.kind == "BUY_NOW") & (rows["mode"] == "cash")]
out = []
for a in ("XAU", "BTC", "ETH", "SOL"):
    b = R.load(a); h1, h4 = b["H1"], b["H4"]
    r4 = rsi(h4["close"]); r4.index = r4.index + pd.Timedelta(hours=4)   # known at the bar close
    hi, lo, cl, idx = h1["high"].to_numpy(), h1["low"].to_numpy(), h1["close"].to_numpy(), h1.index
    end_dev = int(idx.searchsorted(SPLIT)) - 1
    for t, p in zip(buys[buys.asset == a].t, buys[buys.asset == a].price):
        ts = pd.Timestamp(t); k = r4[r4.index <= ts]
        if k.empty: continue
        v = float(k.iloc[-1]); i = int(idx.searchsorted(ts)); last = end_dev if ts < SPLIT else len(cl) - 1
        tgt = p + 15 if a == "XAU" else p * 1.0065; cost = 2.0 if a == "XAU" else p * 0.0015
        w = np.where(hi[i:last + 1] >= tgt)[0]
        if len(w):
            j = i + int(w[0]); net = (tgt - p - cost) / p * 100; dip = lo[i:j + 1].min() / p * 100 - 100; hit24 = int(w[0]) < 24
        else:
            net = (cl[last] - p - cost) / p * 100; dip = lo[i:last + 1].min() / p * 100 - 100; hit24 = False
        out.append({"asset": a, "period": "dev" if ts < SPLIT else "holdout", "hot": v >= 80, "net": net, "dip": dip, "hit24": hit24})
df = pd.DataFrame(out); rep = {}
for per in ("dev", "holdout"):
    for hot, g in df[df.period == per].groupby("hot"):
        rep[f"{per}|{'HOT' if hot else 'NORMAL'}"] = {"buys": len(g), "hit24": round(g.hit24.mean(), 3),
            "median_dip_pct": round(g.dip.median(), 2), "dip_1pct_share": round((g.dip <= -1).mean(), 3), "mean_net_pct": round(g.net.mean(), 3)}
def cmp(per, sign):
    h, n = rep.get(f"{per}|HOT"), rep.get(f"{per}|NORMAL")
    return h and n and sign * (h["mean_net_pct"] - n["mean_net_pct"]) > 0 and sign * (h["hit24"] - n["hit24"]) > 0
rep["verdict"] = "HOT is worse" if all(cmp(p, -1) for p in ("dev", "holdout")) else ("HOT is better" if all(cmp(p, 1) for p in ("dev", "holdout")) else "no clear difference")
(HERE / "rsi_report.json").write_text(json.dumps(rep, indent=1) + "\n"); print(json.dumps(rep, indent=1))
