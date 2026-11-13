"""Evaluate the untouched HOLDOUT period once. Every run is logged in data/holdout_runs.json; the report
warns when the holdout has been used more than once (results then lose their out-of-sample meaning)."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from goldquant import backtest as BT  # noqa: E402
from goldquant.providers.history import HistoryStore  # noqa: E402
from goldquant.providers.twelvedata import SYMBOL  # noqa: E402

DATA = Path(os.environ.get("GOLDQUANT_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))

if __name__ == "__main__":
    hs = HistoryStore(DATA / "history.db")
    b = {tf: hs.load_bars("TwelveData", SYMBOL, tf) for tf in ("M15", "H1", "H4")}
    if len(b["M15"]) < 4000:
        sys.exit("not enough stored live history yet (need >= 4000 M15 bars). Keep the server running in LIVE mode.")
    if input("This consumes the untouched holdout. Type YES to continue: ").strip() != "YES":
        sys.exit("aborted")
    r = BT.run(b["M15"], b["H1"], b["H4"], final=True, registry=DATA / "holdout_runs.json")
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
