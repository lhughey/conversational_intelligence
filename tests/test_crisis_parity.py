"""The Python crisis screen must reproduce `@meddevkit/crisis-signals` exactly.

`tests/fixtures/crisis_parity.jsonl` is the JavaScript package's own output
(regenerate with `scripts/crisis_parity_fixture.mjs`) over its synthetic test
vectors plus edge cases. Offsets there are UTF-16 code units; the port reports
Python string indices, so they are converted before comparing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convint.domain.crisis import PATTERNS_VERSION, screen_text

FIXTURE = Path(__file__).parent / "fixtures" / "crisis_parity.jsonl"
ROWS = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]


def _utf16_to_index(text: str, offset: int) -> int:
    units = 0
    for i, ch in enumerate(text):
        if units >= offset:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
    return len(text)


def _expected(row: dict) -> dict:
    r, text = row["result"], row["text"]
    return {
        "level": r["level"], "immediacy": r["immediacy"], "patterns_version": r["patternsVersion"],
        "findings": [{
            "rule_id": f["ruleId"], "category": f["category"], "base_level": f["baseLevel"],
            "level": f["level"], "start_offset": _utf16_to_index(text, f["startOffset"]),
            "end_offset": _utf16_to_index(text, f["endOffset"]), "text": f["text"],
            "modifiers": f["modifiers"], "subject": f["subject"],
        } for f in r["findings"]],
    }


def test_fixture_covers_the_vendored_patterns():
    assert len(ROWS) > 700
    assert {row["result"]["patternsVersion"] for row in ROWS} == {PATTERNS_VERSION}


@pytest.mark.parametrize("row", ROWS, ids=[row["id"] for row in ROWS])
def test_matches_javascript_package(row):
    got = screen_text(row["text"]).model_dump(exclude={"screener"})
    assert got == _expected(row)
