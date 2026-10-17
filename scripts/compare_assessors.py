"""Compare assessor strategies across models against the seed labels.

Cached by (model, request, rep), so only the first run costs anything.
Each run is recorded under bench-results/ and indexed in HISTORY.md.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from convint.adapters.assessor_deterministic import DeterministicAssessor  # noqa: E402
from convint.adapters.assessor_hybrid import HybridAssessor  # noqa: E402
from convint.adapters.assessor_llm import LLMAssessor  # noqa: E402
from convint.adapters.cache import CachingLLM  # noqa: E402
from convint.adapters.models import build_llm  # noqa: E402
from convint.bench import record as recorder  # noqa: E402
from convint.bench.evaluate import evaluate  # noqa: E402

MODELS = ["haiku-4-5", "haiku-5-5", "sonnet-5", "sonnet-5-5", "opus-5", "opus-5-5", "gpt-4.1-mini", "gpt-4.1"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", default=None,
                        help="what this run is testing (else $NOTE, else '(no note)')")
    args = parser.parse_args(argv)
    prov = recorder.provenance()

    rows: dict = {}
    lines = [f"{'assessor':<26} {'S':>5} {'O':>5} {'both':>6}"]
    print(lines[0])

    def show(label: str, r: dict) -> None:
        rows[label] = r
        line = (f"{label:<26} {r['specificity_exact']:>5.0%} "
                f"{r['ownership_exact']:>5.0%} {r['both_exact']:>6.0%}")
        lines.append(line)
        print(line)

    show("deterministic", evaluate(DeterministicAssessor()))
    for key in MODELS:
        try:
            llm = LLMAssessor(CachingLLM(build_llm(key), mode="rw"))
            for label, assessor in ((f"llm/{key}", llm), (f"hybrid/{key}", HybridAssessor(llm))):
                show(label, evaluate(assessor))
        except Exception as exc:
            rows[f"llm/{key}"] = {"error": str(exc)[:160]}
            line = f"{'llm/'+key:<26} FAILED: {str(exc)[:60]}"
            lines.append(line)
            print(line)

    paths = recorder.record_run(
        "assessors", args.note, rows, render(rows),
        models=[recorder.assessor_model_label(k) for k in MODELS],
        headline=headline(rows), prov=prov,
    )
    print(f"\nrecorded -> {paths['md'].name} (and HISTORY.md)")
    return 0


def headline(rows: dict) -> dict:
    """Per-model `both` (+CI); llm and hybrid side by side."""
    from convint.bench.stats import format_ci

    out = {}
    for name, m in rows.items():
        if "error" in m:
            out[name] = "error"
        else:
            out[f"{name} both"] = format_ci(m["both_exact"], m.get("both_exact_ci"))
    return out


def render(rows: dict) -> str:
    from convint.bench.stats import format_ci

    lines = ["Seed labels: `data/labels/sufficiency.seed.jsonl`. Cells are `rate [95% CI]`,",
             "a cluster bootstrap over the seed set's transcripts. Model calls go",
             "through a read-write cache, so re-runs are free.", "",
             "| assessor | n (k) | specificity | within 1 | ownership | both |",
             "|---|---|---|---|---|---|"]
    for name, m in rows.items():
        if "error" in m:
            lines.append(f"| {name} | — | FAILED: {m['error']} | | | |")
            continue
        cell = lambda k: format_ci(m.get(k), m.get(f"{k}_ci"))  # noqa: E731
        lines.append(f"| {name} | {m.get('n', '?')} (k={m.get('clusters', '?')}) | "
                     f"{cell('specificity_exact')} | {cell('specificity_within_1')} | "
                     f"{cell('ownership_exact')} | {cell('both_exact')} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
