"""Generates android/app/src/main/res/values*/strings.xml from tools/i18n/* and backend/goldquant/msg.py.

English is the default (res/values). Arabic reason texts come straight from the backend catalog, so the server's
text_ar and the app's Arabic can never drift apart. Reason strings use {0},{1} placeholders (rendered by ReasonText),
hence formatted="false"; UI strings use positional %1$s/%1$d.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "i18n"))
sys.path.insert(0, str(ROOT / "backend"))
from goldquant.msg import CATALOG_AR  # noqa: E402
from reasons_en import EN  # noqa: E402
from reasons_fr_es_pt import T  # noqa: E402
from ui_strings import UI  # noqa: E402

RES = ROOT / "android" / "app" / "src" / "main" / "res"
LANGS = [("values", 0), ("values-ar", 1), ("values-fr", 2), ("values-es", 3), ("values-pt-rBR", 4)]


def esc(s: str) -> str:
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    if s.startswith(("@", "?")):
        s = "\\" + s
    return s.replace("\n", "\\n")


def rname(code: str) -> str:
    return "r_" + code.replace(".", "_")


def render(folder: str, idx: int) -> str:
    out = ['<?xml version="1.0" encoding="utf-8"?>', "<resources>"]
    if idx == 0:
        out.append('    <string name="app_name" translatable="false">GOLD AI QUANT</string>')
    for k, v in UI.items():
        out.append(f'    <string name="{k}">{esc(v[idx])}</string>')
    for code in CATALOG_AR:
        if idx == 0:
            text = EN[code]
        elif idx == 1:
            text = CATALOG_AR[code]
        else:
            tr = T.get(code)
            if tr is None:
                continue  # falls back to English through Android's resource fallback
            text = tr[idx - 2]
        out.append(f'    <string name="{rname(code)}" formatted="false">{esc(text)}</string>')
    out.append("</resources>")
    return "\n".join(out) + "\n"


def main() -> None:
    for folder, idx in LANGS:
        d = RES / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / "strings.xml").write_text(render(folder, idx), encoding="utf-8")
    raw = RES / "raw"
    raw.mkdir(exist_ok=True)
    (raw / "keep.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<resources xmlns:tools="http://schemas.android.com/tools" tools:keep="@string/r_*" />\n', encoding="utf-8")
    cov = {f: sum(1 for c in CATALOG_AR if (EN if i == 0 else CATALOG_AR if i == 1 else T).get(c) is not None)
           for f, i in LANGS}
    print("reason-code coverage:", cov, "of", len(CATALOG_AR))


if __name__ == "__main__":
    main()
