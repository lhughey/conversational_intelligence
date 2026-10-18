"""Regenerate contracts/v1/*.json from the pydantic models.

The exported schema is committed. A test asserts the committed files match the
models, so schema drift fails CI instead of surfacing in a consumer.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from convint.api.contract import TurnRequest, TurnResponse  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "contracts" / "v1"

SCHEMAS = {
    "turn-request.schema.json": TurnRequest,
    "turn-response.schema.json": TurnResponse,
}


def render(model) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=OUT,
                        help=f"directory to write the schemas into (default: {OUT})")
    out = parser.parse_args(argv).out
    out.mkdir(parents=True, exist_ok=True)
    for filename, model in SCHEMAS.items():
        (out / filename).write_text(render(model), encoding="utf-8")
        print(f"wrote {out / filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
