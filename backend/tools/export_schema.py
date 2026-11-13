"""Write the JSON Schema of the Decision contract to schema/decision.schema.json."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from goldquant.schemas import Decision  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "schema" / "decision.schema.json"


def render() -> str:
    return json.dumps(Decision.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT}")
