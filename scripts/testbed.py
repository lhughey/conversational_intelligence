"""Comprehensive test stand: run everything, record the result with provenance.

A benchmark number without provenance is a rumour. Every run records the git
SHA, whether the tree was dirty, package versions, dataset hashes and model IDs
alongside the numbers, so a result can be traced back to exactly what produced
it - and so two runs can be compared honestly rather than by filename.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import platform
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
OUT = REPO / "bench-results"


def sh(*cmd: str, cwd: pathlib.Path = REPO) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)


def git_provenance() -> dict:
    _, sha = sh("git", "rev-parse", "HEAD")
    _, branch = sh("git", "rev-parse", "--abbrev-ref", "HEAD")
    code, status = sh("git", "status", "--porcelain")
    dirty = bool(status.strip())
    return {
        "commit": sha.strip(),
        "branch": branch.strip(),
        "dirty": dirty,
        "dirty_files": [l[3:] for l in status.splitlines()][:20] if dirty else [],
    }


def file_hash(path: pathlib.Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def package_versions() -> dict:
    out = {}
    for name in ("pydantic", "anthropic", "openai", "fastapi", "pytest"):
        try:
            mod = __import__(name)
            out[name] = getattr(mod, "__version__", getattr(mod, "VERSION", "?"))
        except Exception:
            out[name] = "not installed"
    return out


def run_pytest(marker: str | None, label: str) -> dict:
    """Parse junit-xml rather than terminal text.

    pytest does not emit its summary line when stdout is not a TTY, so scraping
    it produced "no summary" and would have silently recorded a green run as
    unverified. The XML is structured and always written.
    """
    import tempfile
    import xml.etree.ElementTree as ET

    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as fh:
        xml_path = fh.name
    cmd = [sys.executable, "-m", "pytest", "-q", f"--junit-xml={xml_path}"]
    if marker:
        cmd += ["-m", marker]
    code, _ = sh(*cmd)

    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time": 0.0}
    try:
        root = ET.parse(xml_path).getroot()
        suite = root if root.tag == "testsuite" else root[0]
        counts = {
            "tests": int(suite.get("tests", 0)),
            "failures": int(suite.get("failures", 0)),
            "errors": int(suite.get("errors", 0)),
            "skipped": int(suite.get("skipped", 0)),
            "time": float(suite.get("time", 0)),
        }
    except Exception as exc:  # pragma: no cover
        counts["parse_error"] = str(exc)[:120]
    finally:
        pathlib.Path(xml_path).unlink(missing_ok=True)

    passed = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    summary = (f"{passed} passed, {counts['failures']} failed, "
               f"{counts['errors']} errored, {counts['skipped']} skipped "
               f"in {counts['time']:.2f}s")
    return {"suite": label, "exit_code": code, "ok": code == 0,
            "summary": summary, **counts, "passed": passed}


def run_coverage() -> dict:
    code, output = sh(sys.executable, "-m", "pytest", "-q", "--no-header",
                      "--cov=convint", "--cov-report=term")
    total = next((l for l in output.splitlines() if l.startswith("TOTAL")), "")
    pct = total.split()[-1] if total else "?"
    return {"exit_code": code, "total": pct, "ok": code == 0}


def run_gate_splits() -> dict:
    from convint.bench.gate_eval import run as gate_run

    results = {}
    for split in ("synth", "corpus", "human"):
        try:
            results[split] = gate_run(split)
        except Exception as exc:
            results[split] = {"error": str(exc)[:200]}
    return results


def run_corpus_replay() -> dict:
    from convint.bench import corpus

    result = corpus.run()
    return {k: result[k] for k in ("transcripts", "turns", "actions", "rules")}


def run_assessors(live: bool) -> dict:
    from convint.adapters.assessor_deterministic import DeterministicAssessor
    from convint.bench.evaluate import evaluate

    rows = {"deterministic": evaluate(DeterministicAssessor())}
    if not live:
        return {k: _slim(v) for k, v in rows.items()}

    from convint.adapters.assessor_hybrid import HybridAssessor
    from convint.adapters.assessor_llm import LLMAssessor
    from convint.adapters.cache import CachingLLM
    from convint.adapters.models import build_llm

    for key in ("haiku-4-5", "sonnet-5", "opus-5", "gpt-4.1-mini", "gpt-4.1"):
        try:
            llm = LLMAssessor(CachingLLM(build_llm(key), mode="rw"))
            rows[f"llm/{key}"] = evaluate(llm)
            rows[f"hybrid/{key}"] = evaluate(HybridAssessor(llm))
        except Exception as exc:
            rows[f"llm/{key}"] = {"error": str(exc)[:160]}
    return {k: _slim(v) for k, v in rows.items()}


def _slim(result) -> dict:
    if "error" in result:
        return result
    return {k: result[k] for k in
            ("n", "specificity_exact", "specificity_within_1", "ownership_exact", "both_exact")}


def run_invariant_sampling(samples: int = 6) -> dict:
    """Measure how often generation obeys the single-question rule.

    A stochastic property needs a rate, not a single assertion. Sampling is not
    tunable on the current Opus/Sonnet models, so run-to-run variation is
    inherent and the honest report is a proportion over N draws with the cache
    deliberately OFF.
    """
    from convint.adapters.models import build_llm
    from convint.api.contract import Options, TurnRequest
    from convint.app.turn_engine import TurnEngine
    from convint.domain import (
        ConversationState, InterviewPlan, StageSpec, TopicRecord, TopicSpec, Turn,
    )
    from convint.domain.text import ends_with_question, question_count

    plan = InterviewPlan(
        plan_id="probe",
        stages=[StageSpec(stage_id="early_life", completion_signal="childhood_complete")],
        topics=[TopicSpec(topic_id="childhood", stage="early_life")],
    )
    state = ConversationState(
        turns=[Turn(role="assistant", content="What were you like as a kid?"),
               Turn(role="user", content="I helped at my parents' dry cleaner in Queens.")],
        topics=[TopicRecord(topic_id="childhood", stage="early_life")],
        current_topic_id="childhood",
    )

    single, ends_q, grounded, lengths, errors = 0, 0, 0, [], []
    for _ in range(samples):
        try:
            engine = TurnEngine(llm=build_llm("haiku-4-5"))
            resp = engine.run(TurnRequest(plan=plan, state=state,
                                          options=Options(generate_text=True)))
            text = resp.message.text
            single += question_count(text) == 1
            ends_q += ends_with_question(text)
            grounded += bool(resp.message.grounded_on)
            lengths.append(len(text.split()))
        except Exception as exc:
            errors.append(str(exc)[:120])

    n = samples - len(errors)
    if n == 0:
        return {"samples": samples, "error": errors[0] if errors else "all failed"}
    return {
        "samples": n,
        "single_question_rate": single / n,
        "ends_with_question_rate": ends_q / n,
        "grounded_rate": grounded / n,
        "mean_words": sum(lengths) / len(lengths),
        "errors": errors,
    }


def dataset_stats() -> dict:
    from convint.dataset.build import build
    from convint.dataset.synth import build_from_banks, minimal_pairs
    from convint.bench.gate_eval import load_human_labels

    corpus_items, corpus_labels = build()
    synth_items, synth_labels = build_from_banks()
    return {
        "corpus_items": len(corpus_items),
        "synth_items": len(synth_items),
        "minimal_pairs": len(minimal_pairs(synth_items, synth_labels)),
        "human_labels": len(load_human_labels()),
        "corpus_label_actions": _count(l.action.value for l in corpus_labels),
        "synth_label_actions": _count(l.action.value for l in synth_labels),
    }


def _count(values) -> dict:
    from collections import Counter

    return dict(Counter(values).most_common())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="include model-calling suites")
    parser.add_argument("--tag", default="", help="label for this run")
    args = parser.parse_args()

    started = dt.datetime.now().astimezone()
    print(f"testbed starting {started.isoformat(timespec='seconds')}"
          f"{' (live)' if args.live else ' (offline only)'}\n")

    record: dict = {
        "run_at": started.isoformat(timespec="seconds"),
        "tag": args.tag,
        "live": args.live,
        "git": git_provenance(),
        "platform": {"python": platform.python_version(), "os": platform.platform()},
        "packages": package_versions(),
        "dataset_hashes": {
            p.name: file_hash(p)
            for p in sorted((REPO / "data").rglob("*.jsonl"))
        },
        "suites": [],
    }

    for marker, label in [(None, "offline"), ("e2e", "e2e")] + (
        [("live", "live")] if args.live else []
    ):
        result = run_pytest(marker, label)
        record["suites"].append(result)
        print(f"  {label:<10} {'PASS' if result['ok'] else 'FAIL'}  {result['summary']}")

    record["coverage"] = run_coverage()
    print(f"  {'coverage':<10} {record['coverage']['total']}")

    record["dataset"] = dataset_stats()
    print(f"  {'dataset':<10} corpus={record['dataset']['corpus_items']} "
          f"synth={record['dataset']['synth_items']} "
          f"human={record['dataset']['human_labels']}")

    record["gate"] = run_gate_splits()
    record["corpus_replay"] = run_corpus_replay()
    record["assessors"] = run_assessors(args.live)
    if args.live:
        record["invariants"] = run_invariant_sampling()
        inv = record["invariants"]
        if "error" not in inv:
            print(f"  {'invariants':<10} single-question {inv['single_question_rate']:.0%} "
                  f"of {inv['samples']} samples, grounded {inv['grounded_rate']:.0%}")
    print(f"  {'benchmarks':<10} done")

    stamp = started.strftime("%Y-%m-%dT%H%M%S")
    suffix = f"-{args.tag}" if args.tag else ""
    OUT.mkdir(parents=True, exist_ok=True)
    json_path = OUT / f"testbed-{stamp}{suffix}.json"
    json_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    md_path = OUT / f"testbed-{stamp}{suffix}.md"
    md_path.write_text(render(record), encoding="utf-8")

    (OUT / "LATEST.md").write_text(render(record), encoding="utf-8")

    print(f"\nrecorded -> {json_path.name} / {md_path.name} (and LATEST.md)")
    failed = [s for s in record["suites"] if not s["ok"]]
    return 1 if failed else 0


def render(r: dict) -> str:
    g = r["git"]
    lines = [
        f"# Testbed run — {r['run_at']}",
        "",
        f"**commit** `{g['commit'][:12]}` on `{g['branch']}`"
        + ("  ⚠️ **DIRTY TREE — not reproducible**" if g["dirty"] else ""),
        f"**mode** {'live (model calls made)' if r['live'] else 'offline only'}"
        f" · python {r['platform']['python']}",
        "",
        "## Suites",
        "",
        "| suite | result | detail |",
        "|---|---|---|",
    ]
    for s in r["suites"]:
        lines.append(f"| {s['suite']} | {'PASS' if s['ok'] else '**FAIL**'} | {s['summary']} |")
    total_passed = sum(s.get("passed", 0) for s in r["suites"])
    lines.append(f"| **total** | | **{total_passed} tests passed** |")
    lines += [f"| coverage | {r['coverage']['total']} | statements |", ""]

    d = r["dataset"]
    lines += [
        "## Dataset",
        "",
        f"- corpus items: **{d['corpus_items']}** (weak labels) — {d['corpus_label_actions']}",
        f"- synth items: **{d['synth_items']}** (spec labels) — {d['synth_label_actions']}",
        f"- minimal pairs: **{d['minimal_pairs']}**",
        f"- human-adjudicated: **{d['human_labels']}**",
        "",
        "## Gate evaluation",
        "",
    ]
    for split, res in r["gate"].items():
        if "error" in res:
            lines.append(f"**{split}** — {res['error']}\n")
            continue
        first = next(iter(res.values()))
        lines += [
            f"**{split}** (n={first['n']}, premature denom {first['premature_advance_n']}, "
            f"stall denom {first['stall_n']})",
            "",
            "| policy | acc | premature ↓ | stall ↓ | minimal pairs |",
            "|---|---|---|---|---|",
        ]
        for name, m in res.items():
            pct = lambda v: "n/a" if v is None else f"{v:.0%}"
            lines.append(
                f"| {name} | {m['accuracy_strict']:.0%} | {pct(m['premature_advance_rate'])} "
                f"| {pct(m['stall_rate'])} | {pct(m['minimal_pair_accuracy'])} |"
            )
        lines.append("")

    lines += ["## Assessors", "", "| assessor | n | specificity | within 1 | ownership | both |",
              "|---|---|---|---|---|---|"]
    for name, m in r["assessors"].items():
        if "error" in m:
            lines.append(f"| {name} | — | {m['error']} | | | |")
            continue
        lines.append(
            f"| {name} | {m['n']} | {m['specificity_exact']:.0%} | "
            f"{m['specificity_within_1']:.0%} | {m['ownership_exact']:.0%} | {m['both_exact']:.0%} |"
        )

    inv = r.get("invariants")
    if inv and "error" not in inv:
        lines += ["", "## Generation invariants (live, cache off)", "",
                  f"Measured over {inv['samples']} fresh samples, because sampling is not",
                  "tunable on these models and a single draw cannot establish a rate.", "",
                  "| property | rate |", "|---|---|",
                  f"| exactly one question | {inv['single_question_rate']:.0%} |",
                  f"| ends with the question | {inv['ends_with_question_rate']:.0%} |",
                  f"| grounded in the user's words | {inv['grounded_rate']:.0%} |",
                  f"| mean length | {inv['mean_words']:.0f} words |", ""]

    cr = r["corpus_replay"]
    lines += ["", "## Corpus replay", "",
              f"{cr['transcripts']} transcripts, {cr['turns']} turns",
              "", f"- actions: `{cr['actions']}`", f"- rules fired: `{cr['rules']}`", ""]

    lines += ["## Provenance", "", "```json",
              json.dumps({"packages": r["packages"], "dataset_hashes": r["dataset_hashes"]},
                         indent=2), "```", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
