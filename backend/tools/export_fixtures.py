"""Export real engine outputs (STUB-labelled files use an injected stub model) as contract fixtures shared with the Android unit tests.

BUY/SELL fixtures come from the real engine with an injected stub model (validated=True, p=0.9) and the
critic disabled — they exercise the trade code path and contract, they are NOT market signals."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from goldquant import critic, engine as E  # noqa: E402
from goldquant.providers.demo import DemoProvider  # noqa: E402
from goldquant.schemas import Action, Mode  # noqa: E402
from goldquant.store import Store  # noqa: E402

OUT = [ROOT.parent / "schema" / "fixtures",
       ROOT.parent / "android" / "app" / "src" / "test" / "resources" / "fixtures"]


class _Rep:
    n_oos, qualified, brier_model, brier_climatology, max_reliability_gap = 5000, True, 0.60, 0.65, 0.02


class _StubPath:
    reports = {h: _Rep() for h in (15, 30, 60, 240)}

    def predict(self, row):
        return {h: np.array([0.58, 0.30, 0.12]) for h in (15, 30, 60, 240)}


class _Paths(E.PathService):
    def get(self, provider, as_of, bars):
        return E.PathState(_StubPath(), True, "stub", None)


def main():
    demo = DemoProvider()
    real = E.DecisionEngine(Store())
    fx = {"wait_demo.json": real.decide(demo, Mode.DEMO, (pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=7)).to_pydatetime()),
          "unavailable_live.json": real.decide(None, Mode.LIVE, demo.default_as_of())}
    E.review = lambda *a, **k: critic.CriticResult()
    E.anti_trade = lambda c: [] if c.direction else ["no direction"]
    from goldquant.reliability import court as C
    C.evidence_judge = lambda *a, **k: C.Judgement("evidence", True, [])
    C.risk_judge = lambda *a, **k: C.Judgement("risk_governor", True, [])
    stub = E.DecisionEngine(Store(), _Paths())
    for h in range(0, 400, 3):
        d = stub.decide(demo, Mode.DEMO, (pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=h)).to_pydatetime())
        if d.action in (Action.BUY, Action.SELL) and f"{d.action.value.lower()}_demo_stub.json" not in fx:
            fx[f"{d.action.value.lower()}_demo_stub.json"] = d
        if len(fx) == 4:
            break
    class _Prec:  # stub: calibration "passed" so the LIVE contract example carries probabilities
        def promoted(self):
            return set()

        def calibration_ok(self):
            return True

        def evaluate_now(self, *a):
            return {"p_tp_cal": 0.58, "p_sl_cal": 0.30, "p_none_cal": 0.12, "meta_p": None, "accept": {},
                    "n_cal": 500, "disagreement": 0.02}
    stub.precision = _Prec()
    for h in range(0, 400, 3):  # LIVE-mode contract example with (stub) qualified probabilities
        d = stub.decide(demo, Mode.LIVE, (pd.Timestamp(demo.default_as_of()) - pd.Timedelta(hours=h)).to_pydatetime())
        if d.action in (Action.BUY, Action.SELL):
            fx["live_qualified_stub.json"] = d
            break
    for out in OUT:
        out.mkdir(parents=True, exist_ok=True)
        for name, d in fx.items():
            (out / name).write_text(d.model_dump_json(indent=2), encoding="utf-8")
    print("exported:", sorted(fx))


if __name__ == "__main__":
    main()
