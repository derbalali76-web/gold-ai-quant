"""V7: reason codes + Android localisation consistency (all checks are static / deterministic)."""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from goldquant import outlook as OL
from goldquant.msg import CATALOG_AR, M, Msg, cut_short, ref_dict
from goldquant.schemas import Decision

ROOT = Path(__file__).resolve().parents[2]
PKG = Path(__file__).resolve().parents[1] / "goldquant"
RES = ROOT / "android" / "app" / "src" / "main" / "res"
KOTLIN = ROOT / "android" / "app" / "src" / "main" / "java"
sys.path.insert(0, str(ROOT / "tools" / "i18n"))
from reasons_en import EN  # noqa: E402
from reasons_fr_es_pt import T  # noqa: E402
from ui_strings import UI  # noqa: E402

PLACEHOLDER = re.compile(r"\{\d+\}")


def _strings(folder: str) -> dict:
    root = ET.parse(RES / folder / "strings.xml").getroot()
    return {e.get("name"): e.text or "" for e in root.findall("string")}


def test_every_code_used_in_the_backend_exists_in_the_catalog():
    used = set()
    for f in PKG.rglob("*.py"):
        if f.name == "msg.py":
            continue
        used |= set(re.findall(r"""\b(?:M|Mg)\(\s*\(?\s*["']([a-z]{1,3}\.[a-z0-9_]+)["']""", f.read_text(encoding="utf-8")))
    assert used, "no reason codes found - scan pattern broke"
    assert used <= set(CATALOG_AR), sorted(used - set(CATALOG_AR))


def test_msg_keeps_arabic_text_and_serialises_nested_references():
    m = M("rs.ctx", M("w.up"), M("w.down"), M("rs.tail_above", "4000.00"))
    assert isinstance(m, Msg) and m == "اتجاه H4 صاعد والاتجاه العام هابط، والسعر فوق الدعم 4000.00"
    ref = ref_dict(m)
    assert ref["code"] == "rs.ctx" and ref["args"][0]["code"] == "w.up" and ref["args"][2]["args"] == ["4000.00"]
    assert ref_dict("plain")["code"] == "raw"
    assert cut_short("a؛ b") == "a"


def test_english_covers_every_code_and_placeholders_match_in_all_languages():
    assert set(EN) == set(CATALOG_AR)
    for code, ar in CATALOG_AR.items():
        want = sorted(PLACEHOLDER.findall(ar))
        assert sorted(PLACEHOLDER.findall(EN[code])) == want, code
        for lang in T.get(code, ()):
            assert sorted(PLACEHOLDER.findall(lang)) == want, code
    assert set(T) <= set(EN)


def test_android_resources_match_the_catalog_and_each_other():
    default = _strings("values")
    for code in CATALOG_AR:
        assert "r_" + code.replace(".", "_") in default, code
    for folder in ("values-ar", "values-fr", "values-es", "values-pt-rBR"):
        s = _strings(folder)
        assert set(s) <= set(default), (folder, sorted(set(s) - set(default)))
        for k, v in s.items():
            if k.startswith("r_"):
                continue
            want = sorted(re.findall(r"%\d\$[sd]", default[k]))
            assert sorted(re.findall(r"%\d\$[sd]", v)) == want, (folder, k)
        ui_missing = [k for k in UI if k not in s]
        assert not ui_missing, (folder, ui_missing)  # every UI string exists in all 5 languages
    ar = _strings("values-ar")
    assert all(ar["r_" + c.replace(".", "_")] == t for c, t in CATALOG_AR.items()
               if "'" not in t and '"' not in t and "\\" not in t)  # Arabic app text == server text_ar


def test_kotlin_uses_only_existing_strings_and_has_no_hardcoded_arabic():
    default = _strings("values")
    used = set()
    for f in KOTLIN.rglob("*.kt"):
        text = f.read_text(encoding="utf-8")
        used |= set(re.findall(r"R\.string\.([a-z0-9_]+)", text))
        if f.name == "Lang.kt":  # native language names are shown as written in their own language
            continue
        arabic = re.findall(r'"[^"\n]*[؀-ۿ][^"\n]*"', text)
        assert not arabic, (f.name, arabic[:3])
    assert used <= set(default), sorted(used - set(default))


def test_decision_carries_refs_for_main_messages_and_horizons():
    import pandas as pd
    from goldquant.engine import DecisionEngine
    from goldquant.providers.demo import DemoProvider
    from goldquant.schemas import Mode
    from goldquant.store import Store
    prov = DemoProvider()
    t = (pd.Timestamp(prov.default_as_of()) - pd.Timedelta(hours=3)).to_pydatetime()
    d = DecisionEngine(Store()).decide(prov, Mode.DEMO, t)
    assert d.action.value == "UNAVAILABLE" or d.reason_short_ref is not None
    assert d.outlooks and all(o.stance_ref is not None for o in d.outlooks)
    for o in d.outlooks:
        if o.horizon != "HOURS":
            assert o.levels is not None and o.trend is not None
            assert all(z.strength is None for z in o.levels.supports + o.levels.resistances)
            assert not o.probabilities_available


def test_msg_pickle_and_copy_roundtrip():
    import copy
    import pickle
    from goldquant.msg import M, Msg
    m = M("md.no_provider")
    for r in (pickle.loads(pickle.dumps(m)), copy.copy(m), copy.deepcopy(m)):
        assert isinstance(r, Msg) and r.code == m.code and r.args == m.args and str(r) == str(m)


def test_live_track_fields_are_counts_not_probabilities():
    import pytest
    from goldquant.schemas import HorizonOutlook, SCHEMA_VERSION
    assert tuple(map(int, SCHEMA_VERSION.split("."))) >= (1, 6, 0)
    o = HorizonOutlook(horizon="WEEK", label_ar="أسبوع", action="WAIT", stance_ar="x", reason_ar="y")
    assert o.live_resolved == 0 and o.live_hits == 0
    with pytest.raises(Exception):
        HorizonOutlook(horizon="WEEK", label_ar="أسبوع", action="WAIT", stance_ar="x", reason_ar="y", live_hits=-1)


def test_live_decision_carries_live_track(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    from goldquant.api import create_app, Settings
    from goldquant.providers.demo import DemoProvider
    monkeypatch.setenv("GOLDQUANT_BG_REFRESH", "0")
    (tmp_path / "outlook_track.json").write_text(json.dumps(
        {"horizons": {"WEEK": {"resolved": 12, "hits": 7}, "MONTH": {"resolved": 3, "hits": 1}}}), encoding="utf-8")
    st = Settings.from_env(str(tmp_path))
    c = TestClient(create_app(str(tmp_path / "g.db"), settings=st, live_provider=DemoProvider()))
    d = c.get("/decision", params={"mode": "LIVE"}).json()
    by = {o["horizon"]: o for o in d["outlooks"]}
    if "WEEK" in by:
        assert (by["WEEK"]["live_resolved"], by["WEEK"]["live_hits"]) == (12, 7)
    if "MONTH" in by:
        assert (by["MONTH"]["live_resolved"], by["MONTH"]["live_hits"]) == (3, 1)
    assert all(o["live_hits"] <= o["live_resolved"] for o in d["outlooks"])
