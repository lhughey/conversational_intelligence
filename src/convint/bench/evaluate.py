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
from .stats import format_ci, rate_summary

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


def evaluate(assessor, labels: list[dict] | None = None,
             *, seed: int = 0, n_boot: int = 2000) -> Result:
    """Agreement rates, each with a transcript-level cluster-bootstrap CI.

    Cluster = the label's `transcript`: turns of one golden share a persona and
    an author, so the effective n is the number of transcripts (4 today), not
    the number of labelled turns. Adds `<metric>_ci` ([lo, hi] or None),
    `<metric>_n` and `<metric>_k` beside each existing rate.
    """
    labels = labels or load_labels()
    cases = []
    for label in labels:
        text = load_turn(label["transcript"], label["turn_index"])
        if not text.startswith(label["text_prefix"]):
            raise ValueError(
                f"fixture drift: {label['transcript']}#{label['turn_index']} no longer "
                "matches its label. Re-label rather than silently re-scoring."
            )
        cases.append({
            "id": f"{label['transcript']}#{label['turn_index']}",
            "text": text,
            "specificity": label["specificity"],
            "ownership": label["ownership"],
            "cluster": label["transcript"],
            "note": label["note"],
        })
    return score(assessor, cases, cluster_unit="transcripts", seed=seed, n_boot=n_boot)


def score(assessor, cases: list[dict], *, cluster_unit: str,
          seed: int = 0, n_boot: int = 2000) -> Result:
    """Score an assessor on prepared cases; shared by every labelled split.

    Each case is `{id, text, specificity, ownership, cluster, note}`. Every
    turn is assessed in isolation (empty prior), in the order given. The rows
    carry ids and labels only - never the text - so a report built from them
    cannot leak item content.
    """
    rows, s_exact, o_exact, s_within1 = [], 0, 0, 0
    flags: dict[str, list[bool]] = {
        "specificity_exact": [], "specificity_within_1": [],
        "ownership_exact": [], "both_exact": [],
    }
    clusters: list[str] = []
    confusion: Counter = Counter()
    o_confusion: Counter = Counter()

    for case in cases:
        got = assessor.assess(case["text"], SufficiencyComponents())
        want_s = Specificity(case["specificity"])
        want_o = Ownership(case["ownership"])

        s_ok = got.specificity is want_s
        o_ok = got.ownership is want_o
        s_exact += s_ok
        o_exact += o_ok
        s_within1 += abs(got.specificity.rank - want_s.rank) <= 1
        confusion[(want_s.value, got.specificity.value)] += 1
        o_confusion[(want_o.value, got.ownership.value)] += 1
        within1 = abs(got.specificity.rank - want_s.rank) <= 1
        clusters.append(case["cluster"])
        flags["specificity_exact"].append(s_ok)
        flags["specificity_within_1"].append(within1)
        flags["ownership_exact"].append(o_ok)
        flags["both_exact"].append(s_ok and o_ok)

        rows.append({
            "id": case["id"],
            "want": f"{want_s.value}/{want_o.value}",
            "got": f"{got.specificity.value}/{got.ownership.value}",
            "ok": s_ok and o_ok,
            "note": case.get("note", ""),
        })

    n = len(cases)
    if n == 0:
        raise ValueError("nothing to score: no labelled cases")
    result = Result(
        assessor=getattr(assessor, "name", type(assessor).__name__),
        n=n,
        clusters=len(set(clusters)),
        cluster_unit=cluster_unit,
        specificity_exact=s_exact / n,
        specificity_within_1=s_within1 / n,
        ownership_exact=o_exact / n,
        both_exact=sum(r["ok"] for r in rows) / n,
        confusion={f"{k[0]}->{k[1]}": v for k, v in sorted(confusion.items())},
        ownership_confusion={f"{k[0]}->{k[1]}": v for k, v in sorted(o_confusion.items())},
        rows=rows,
    )
    for metric, values in flags.items():
        summary = rate_summary(values, clusters, seed=seed, n_boot=n_boot)
        result[f"{metric}_ci"] = summary["ci"]
        result[f"{metric}_n"] = summary["n"]
        result[f"{metric}_k"] = summary["k"]
    return result


def format_report(result: Result) -> str:
    def row(metric: str) -> str:
        return format_ci(result[metric], result.get(f"{metric}_ci"),
                         result.get(f"{metric}_n"), result.get(f"{metric}_k"),
                         result.get("cluster_unit", "transcripts"))

    lines = [
        f"assessor: {result['assessor']}   n={result['n']}",
        "  (95% transcript-level cluster-bootstrap CI in brackets)",
        "",
        f"  specificity exact      {row('specificity_exact')}",
        f"  specificity within 1   {row('specificity_within_1')}",
        f"  ownership exact        {row('ownership_exact')}",
        f"  both exact             {row('both_exact')}",
        "",
        "  misses:",
    ]
    misses = [r for r in result["rows"] if not r["ok"]]
    lines += [f"    {r['id']:<28} want {r['want']}  got {r['got']}   ({r['note']})" for r in misses]
    if not misses:
        lines.append("    none")
    return "\n".join(lines)
