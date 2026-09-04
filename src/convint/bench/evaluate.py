"""Benchmark: how well does an assessor agree with hand labels?

The seed label set is small (~23 items) and hand-labeled by one person, so it
detects a badly broken assessor and cannot rank two good ones. It is a floor,
not a leaderboard. Treat any single number from it as directional.
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter

from ..domain.enums import Ownership, Specificity
from ..domain.sufficiency import SufficiencyComponents

REPO = pathlib.Path(__file__).resolve().parents[3]
LABELS = REPO / "data" / "labels" / "sufficiency.seed.jsonl"
GOLDENS = REPO / "docs" / "golden-transcripts"


def load_labels(path: pathlib.Path | None = None) -> list[dict]:
    path = path or LABELS
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_turn(transcript: str, index: int) -> str:
    data = json.loads((GOLDENS / f"{transcript}.json").read_text(encoding="utf-8"))
    return data["userTurns"][index]


class Result(dict):
    """Plain dict so it serialises straight to JSON."""


def evaluate(assessor, labels: list[dict] | None = None) -> Result:
    labels = labels or load_labels()
    rows, s_exact, o_exact, s_within1 = [], 0, 0, 0
    confusion: Counter = Counter()

    for label in labels:
        text = load_turn(label["transcript"], label["turn_index"])
        if not text.startswith(label["text_prefix"]):
            raise ValueError(
                f"fixture drift: {label['transcript']}#{label['turn_index']} no longer "
                "matches its label. Re-label rather than silently re-scoring."
            )
        got = assessor.assess(text, SufficiencyComponents())
        want_s = Specificity(label["specificity"])
        want_o = Ownership(label["ownership"])

        s_ok = got.specificity is want_s
        o_ok = got.ownership is want_o
        s_exact += s_ok
        o_exact += o_ok
        s_within1 += abs(got.specificity.rank - want_s.rank) <= 1
        confusion[(want_s.value, got.specificity.value)] += 1

        rows.append({
            "id": f"{label['transcript']}#{label['turn_index']}",
            "want": f"{want_s.value}/{want_o.value}",
            "got": f"{got.specificity.value}/{got.ownership.value}",
            "ok": s_ok and o_ok,
            "note": label["note"],
        })

    n = len(labels)
    return Result(
        assessor=getattr(assessor, "name", type(assessor).__name__),
        n=n,
        specificity_exact=s_exact / n,
        specificity_within_1=s_within1 / n,
        ownership_exact=o_exact / n,
        both_exact=sum(r["ok"] for r in rows) / n,
        confusion={f"{k[0]}->{k[1]}": v for k, v in sorted(confusion.items())},
        rows=rows,
    )


def format_report(result: Result) -> str:
    lines = [
        f"assessor: {result['assessor']}   n={result['n']}",
        "",
        f"  specificity exact      {result['specificity_exact']:.0%}",
        f"  specificity within 1   {result['specificity_within_1']:.0%}",
        f"  ownership exact        {result['ownership_exact']:.0%}",
        f"  both exact             {result['both_exact']:.0%}",
        "",
        "  misses:",
    ]
    misses = [r for r in result["rows"] if not r["ok"]]
    lines += [f"    {r['id']:<28} want {r['want']}  got {r['got']}   ({r['note']})" for r in misses]
    if not misses:
        lines.append("    none")
    return "\n".join(lines)
