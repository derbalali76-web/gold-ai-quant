"""Run the full V3 precision evaluation and the promotion gate; writes data/precision_report.json and
data/promotions.json. Uses stored LIVE history when available (>= 4000 M15 bars), else the synthetic set —
synthetic results are written for inspection but can NEVER promote anything (promotion.promoted checks it)."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from goldquant.precision import promotion as PR  # noqa: E402
from goldquant.precision.report import full_report  # noqa: E402
from goldquant.providers.demo import DemoProvider  # noqa: E402
from goldquant.providers.history import HistoryStore  # noqa: E402
from goldquant.providers.twelvedata import SYMBOL  # noqa: E402

DATA = Path(os.environ.get("GOLDQUANT_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))

if __name__ == "__main__":
    hs = HistoryStore(DATA / "history.db")
    b = {tf: hs.load_bars("TwelveData", SYMBOL, tf) for tf in ("M15", "H1", "H4")}
    if len(b["M15"]) >= 4000 and len(b["H4"]) >= 300:
        label = "LIVE HISTORY (TwelveData)"
    else:
        demo = DemoProvider()
        b = {tf: demo.bars(tf, demo.default_as_of(), 20000).df for tf in ("M15", "H1", "H4")}
        label = "SYNTHETIC DEMO"
    rep = full_report(b["M15"], b["H1"], b["H4"], label)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "precision_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    PR.save(DATA / "promotions.json", rep.get("promotion", []), label)
    print("dataset:", label)
    for k, v in rep.get("rules", {}).items():
        print(f"{k:22s} n={v['accepted']:5d} win={v['win_rate']} ci={v['win_rate_ci95']} ev={v['ev_per_trade']} ev_ci={v['ev_ci95']}")
    for p in rep.get("promotion", []):
        print("PROMOTION", p["candidate"], p["promoted"], p["reasons_ar"])
