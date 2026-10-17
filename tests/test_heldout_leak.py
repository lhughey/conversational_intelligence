"""Leak guard for the held-out sufficiency set.

THE RULE (data/heldout/README.md): the held-out set is never used for tuning,
prompt optimization, few-shot examples, or choosing a prompt by reading its
misses. A number from it is an estimate only while nothing has learned from it.

Two things enforce that mechanically:

1. No held-out id or text appears in anything that has been - or will be -
   tuned against or served as material: the seed sufficiency labels, the
   golden transcripts they point into, the turn-decision data, the persona
   banks synth builds from, and any prompt or few-shot text under `src/`.
   Long items are checked by 8-word shingles (so a paraphrased copy of a
   sentence is caught, not just a verbatim item); short items by exact match.

2. Only evaluation code reads the set. Any file under `src/convint/` or
   `scripts/` that mentions it must be on READERS below. Never add a
   prompt-optimization, few-shot-selection, training or generation module to
   that list - that is precisely the use the set exists to exclude. Adding
   an evaluation script is fine; say why in the commit.
"""

from __future__ import annotations

import json
import pathlib
import re

from convint.bench import heldout
from convint.dataset.bank import BANKS, load_personas
from convint.dataset.synth import build_from_banks

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "convint"
SHINGLE = 8

#: The only files allowed to read (or name) the held-out set.
READERS = {
    "src/convint/bench/heldout.py",          # the loader + scoring
    "src/convint/dataset/label_heldout.py",  # the user's labelling flow
    "src/convint/api/cli.py",                # dispatch to the two above
    "scripts/compare_assessors.py",          # assessor benchmark
    "scripts/cascade_analysis.py",           # cascade benchmark
    "scripts/testbed.py",                    # records benchmark runs
}
#: Packages that must never see it, whatever READERS says.
FORBIDDEN_PACKAGES = ("adapters", "app", "domain", "ports")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _shingles(tokens: list[str], n: int = SHINGLE) -> set[tuple[str, ...]]:
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return []


def _json_strings(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [s for line in text.splitlines() if line.strip() for s in _strings(json.loads(line))]
    return _strings(json.loads(text))


def _src_files() -> list[pathlib.Path]:
    return sorted(p for p in SRC.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts
                  and p.suffix in {".py", ".json", ".jsonl", ".md", ".txt", ".yaml", ".yml"})


def _targets() -> dict[str, list[str]]:
    """name -> text units that must not contain held-out material."""
    targets: dict[str, list[str]] = {}
    seed = REPO / "data" / "labels" / "sufficiency.seed.jsonl"
    targets[str(seed.relative_to(REPO))] = _json_strings(seed)
    for p in sorted((REPO / "docs" / "golden-transcripts").rglob("*.json")):
        targets[str(p.relative_to(REPO))] = _json_strings(p)
    for p in sorted((REPO / "docs").glob("questions.*")):
        targets[str(p.relative_to(REPO))] = (
            _json_strings(p) if p.suffix == ".json" else [p.read_text(encoding="utf-8")])
    for p in sorted((REPO / "data" / "turn_decisions").glob("*.jsonl")):
        targets[str(p.relative_to(REPO))] = _json_strings(p)
    for p in sorted(BANKS.glob("*.persona.json")):
        targets[str(p.relative_to(REPO))] = _json_strings(p)
    synth_items, _ = build_from_banks()
    targets["synth (built from banks)"] = [t for i in synth_items for t in i.user_turns]
    for p in _src_files():
        text = p.read_text(encoding="utf-8")
        # whole file (prompts, docstrings) plus every quoted span, so a short
        # example inside a prompt ("yes, that lands") is a unit of its own
        quoted = re.findall(r'"([^"\n]{1,300})"', text) + re.findall(r"'([^'\n]{1,300})'", text)
        targets[str(p.relative_to(REPO))] = [text, *quoted]
    return targets


def test_targets_are_actually_scanned():
    """A guard that scans nothing passes vacuously; make sure it does not."""
    targets = _targets()
    assert any(k.startswith("docs/golden-transcripts/") for k in targets)
    assert "src/convint/adapters/assessor_llm.py" in targets
    assert "data/labels/sufficiency.seed.jsonl" in targets
    assert any(k.startswith("data/personas/") for k in targets)
    assert sum(len(v) for v in targets.values()) > 500


def _leaks(items, targets: dict[str, list[str]]) -> list[str]:
    target_shingles = {name: set().union(*(_shingles(_tokens(u)) for u in units))
                       for name, units in targets.items()}
    target_units = {name: {tuple(_tokens(u)) for u in units} for name, units in targets.items()}

    leaks = []
    for item in items:
        toks = _tokens(item.text)
        if len(toks) >= SHINGLE:
            mine = _shingles(toks)
            for name, theirs in target_shingles.items():
                hit = mine & theirs
                if hit:
                    leaks.append(f"{item.id} shares '{' '.join(sorted(hit)[0])}' with {name}")
        else:
            for name, units in target_units.items():
                if tuple(toks) in units:
                    leaks.append(f"{item.id} ({item.text!r}) is verbatim in {name}")
    return leaks


def test_no_heldout_text_in_seed_turn_decisions_banks_or_prompts():
    leaks = _leaks(heldout.load_items(), _targets())
    assert not leaks, "held-out text leaked:\n  " + "\n  ".join(leaks)


def test_the_detector_catches_a_reworded_copy_and_a_short_verbatim_one():
    items = heldout.load_items()
    long_item = max(items, key=lambda i: len(i.text))
    short_item = min(items, key=lambda i: len(i.text))
    words = long_item.text.split()
    reworded = "As an example: " + " ".join(words[2:2 + SHINGLE + 2]) + " - and so on."
    targets = {"fake few-shot prompt": [reworded],
               "fake prompt literal": [short_item.text.upper()],
               "unrelated": ["nothing to see here"]}
    leaks = _leaks(items, targets)
    assert any(long_item.id in l and "few-shot" in l for l in leaks)
    assert any(short_item.id in l and "literal" in l for l in leaks)
    assert not any("unrelated" in l for l in leaks)


def test_no_heldout_id_outside_the_heldout_set():
    ids = {i.id for i in heldout.load_items()}
    roots = [REPO / "src", REPO / "scripts", REPO / "docs", REPO / "data"]
    found = []
    for root in roots:
        for p in root.rglob("*"):
            if (not p.is_file() or "__pycache__" in p.parts or p.suffix == ".zip"
                    or heldout.DIR in p.parents):
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            found += [f"{i} in {p.relative_to(REPO)}" for i in ids if i in text]
    assert not found, found


def test_heldout_personas_are_not_synth_banks():
    """Synth and the gate benchmarks build from data/personas/. A held-out
    persona there would turn its texts into served, tuned-against material."""
    held = {p.stem.removesuffix(".persona") for p in heldout.PERSONAS.glob("*.persona.json")}
    assert held
    assert not held & {p.persona_id for p in load_personas()}
    assert not any((BANKS / f"{h}.persona.json").exists() for h in held)
    assert heldout.DIR not in BANKS.parents and BANKS != heldout.PERSONAS


def test_only_evaluation_code_reads_the_heldout_set():
    mentions = set()
    for root in (SRC, REPO / "scripts"):
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            if re.search(r"held[-_ ]?out", p.read_text(encoding="utf-8"), re.I):
                mentions.add(str(p.relative_to(REPO)))
    # bench/* other than the loader may score with it, via the loader
    allowed = READERS | {m for m in mentions if m.startswith("src/convint/bench/")}
    assert mentions <= allowed, (
        f"not allowed to read the held-out set: {sorted(mentions - allowed)} - "
        "see this test's docstring before adding to READERS")
    for m in mentions:
        parts = pathlib.Path(m).parts
        assert not (len(parts) > 2 and parts[2] in FORBIDDEN_PACKAGES), m
    assert "src/convint/bench/heldout.py" in mentions  # the guard is looking somewhere real


def test_labelling_flow_never_reads_the_author_rung():
    """Showing (or even loading) intended.jsonl would anchor the labeller."""
    source = (SRC / "dataset" / "label_heldout.py").read_text(encoding="utf-8")
    assert not re.search(r"intended", source, re.I)
