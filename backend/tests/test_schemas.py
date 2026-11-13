from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from goldquant.schemas import Action, CourtJudgement, DataFreshness, Decision, Mode, SpotOrProxy

COURT_OK = [CourtJudgement(judge=j, passed=True) for j in ("statistics", "evidence", "risk_governor")]

NOW = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)


def base(**kw):
    d = dict(decision_id="x", mode=Mode.LIVE, action=Action.WAIT, spot_or_proxy=SpotOrProxy.SPOT, provider="p",
             analyzed_at_utc=NOW, model_version="m", data_quality="GOOD", snapshot_hash="h",
             data_freshness=DataFreshness(quote_age_seconds=5, max_allowed_seconds=180, is_fresh=True))
    d.update(kw)
    return d


def trade(action=Action.BUY, **kw):
    lv = dict(quote=2000.0, quote_timestamp_utc=NOW, entry_min=1999.5, entry_max=2000.5, stop_loss=1995.0,
              tp1=2005.0, horizon_minutes=240, valid_until_utc=NOW + timedelta(minutes=15), court=COURT_OK)
    if action == Action.SELL:
        lv.update(stop_loss=2005.0, tp1=1995.0)
    lv.update(kw)
    return base(action=action, **lv)


def test_valid_buy_and_sell():
    Decision(**trade(Action.BUY))
    Decision(**trade(Action.SELL))


@pytest.mark.parametrize("bad", [dict(stop_loss=2001.0), dict(tp1=1999.0), dict(entry_min=2001.0)])
def test_inconsistent_buy_levels_rejected(bad):
    with pytest.raises(ValidationError):
        Decision(**trade(Action.BUY, **bad))


def test_trade_requires_levels():
    with pytest.raises(ValidationError):
        Decision(**trade(Action.BUY, stop_loss=None))


def test_trade_on_stale_data_rejected():
    stale = DataFreshness(quote_age_seconds=900, max_allowed_seconds=180, is_fresh=False)
    with pytest.raises(ValidationError):
        Decision(**trade(Action.BUY, data_freshness=stale))


def test_probability_never_in_demo():
    with pytest.raises(ValidationError):
        Decision(**base(mode=Mode.DEMO, spot_or_proxy=SpotOrProxy.SYNTHETIC,
                        probability_target_before_stop=0.7, calibration_sample_count=5000))


def test_probability_requires_calibration_samples():
    with pytest.raises(ValidationError):
        Decision(**base(probability_target_before_stop=0.7, calibration_sample_count=50))
    Decision(**base(probability_target_before_stop=0.7, calibration_sample_count=300))


def test_demo_must_be_labelled_synthetic():
    with pytest.raises(ValidationError):
        Decision(**base(mode=Mode.DEMO, spot_or_proxy=SpotOrProxy.SPOT))


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        Decision(**base(guaranteed_win_rate=0.95))


def test_committed_json_schema_is_current():
    from tools.export_schema import OUT, render
    assert OUT.read_text(encoding="utf-8") == render(), "run: python tools/export_schema.py"


def test_shared_fixtures_match_contract():
    """Fixtures consumed by the Android parser tests must stay valid against the backend contract."""
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    a = sorted((root / "schema" / "fixtures").glob("*.json"))
    b = sorted((root / "android/app/src/test/resources/fixtures").glob("*.json"))
    assert [p.name for p in a] == [p.name for p in b] and len(a) >= 4
    for p, q in zip(a, b):
        assert p.read_text() == q.read_text()
        Decision(**json.loads(p.read_text()))


def test_trade_requires_every_court_judge():
    with pytest.raises(ValidationError):
        Decision(**trade(Action.BUY, court=[]))
    bad = [CourtJudgement(judge="statistics", passed=True), CourtJudgement(judge="risk_governor", passed=False)]
    with pytest.raises(ValidationError):
        Decision(**trade(Action.BUY, court=bad))
