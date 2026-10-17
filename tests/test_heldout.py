"""Held-out sufficiency set: loader, labelling flow, and the scoring gate.

Every test that writes labels writes them to a temp file; the committed
`data/heldout/labels.jsonl` belongs to the user.
"""

from __future__ import annotations

import json
import re

import pytest

from convint.adapters.assessor_deterministic import DeterministicAssessor
from convint.api.cli import main as cli_main
from convint.bench import heldout
from convint.dataset import label_heldout
from convint.dataset.bank import Persona
from convint.domain.enums import Ownership, Specificity

PERSONAS = {"wren", "hollis", "lucian"}
#: names the goldens and the seed banks already use; held-out personas are new
USED_NAMES = {"maya", "rachel", "elena", "sam", "daniel", "marcus", "dana", "priya"}


@pytest.fixture(scope="module")
def items():
    return heldout.load_items()


@pytest.fixture(scope="module")
def intended():
    return heldout.load_intended()


def _label(path, items, intended, n):
    """Label the first n items of the presentation order with the author's rung."""
    chosen = heldout.presentation_order(items)[:n]
    for item in chosen:
        want = intended[item.id]
        heldout.append_label(heldout.make_label(item, want["specificity"], want["ownership"]),
                             path)
    return chosen


class _Script:
    """Feeds scripted answers to run_session; records every prompt."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.answers:
            raise AssertionError(f"session asked more than scripted: {prompt!r}")
        return self.answers.pop(0)


# -- the committed set -------------------------------------------------------

def test_items_load_and_are_well_formed(items):
    assert 55 <= len(items) <= 75
    assert {i.persona for i in items} == PERSONAS
    for persona in PERSONAS:
        assert sum(i.persona == persona for i in items) >= 18, persona
    for item in items:
        assert re.fullmatch(r"ho-[0-9a-f]{6}", item.id), item.id
        assert item.question.strip() and item.text.strip()


def test_persona_files_validate_and_carry_no_labels(items):
    """Persona files hold metadata only. Rungs would carry a specificity and
    ownership per text - the author's rung - so they stay empty here."""
    files = sorted(heldout.PERSONAS.glob("*.persona.json"))
    personas = {p.persona_id: p for p in
                (Persona.model_validate_json(f.read_text(encoding="utf-8")) for f in files)}
    assert set(personas) == PERSONAS
    assert not set(personas) & USED_NAMES
    for persona in personas.values():
        assert persona.synthetic
        assert all(t.rungs == [] for t in persona.topics), persona.persona_id
    for item in items:
        assert personas[item.persona].topic(item.topic) is not None, (item.id, item.topic)


def test_author_rung_is_stored_separately_and_spans_the_grid(items, intended):
    assert set(intended) == {i.id for i in items}
    rows = list(intended.values())
    for s in ("S0", "S1", "S2", "S3"):
        assert sum(r["specificity"] == s for r in rows) >= 5, s
    for o in ("O0", "O1", "O2"):
        assert sum(r["ownership"] == o for r in rows) >= 5, o
    boundaries = {r["boundary"] for r in rows if r["boundary"]}
    assert {"S1/S2", "S2/S3", "O0/O1", "O1/O2"} <= boundaries


def test_minimal_pairs_share_persona_and_topic_and_differ_in_the_rung(items, intended):
    by_id = {i.id: i for i in items}
    pairs: dict[str, list[str]] = {}
    for item_id, row in intended.items():
        if row["pair"]:
            pairs.setdefault(row["pair"], []).append(item_id)
    assert len(pairs) >= 6
    for name, members in pairs.items():
        assert len(members) == 2, name
        a, b = (by_id[m] for m in members)
        assert (a.persona, a.topic) == (b.persona, b.topic), name
        ra, rb = intended[a.id], intended[b.id]
        assert (ra["specificity"], ra["ownership"]) != (rb["specificity"], rb["ownership"]), name


def test_committed_labels_file_exists_and_is_consistent(items):
    """It starts empty and fills as the user labels; either way it must parse
    against the current items (no unknown ids, no text drift)."""
    assert heldout.LABELS.exists()
    heldout.load_labels(items=items)


def test_presentation_order_is_seeded_and_not_file_order(items):
    first = [i.id for i in heldout.presentation_order(items)]
    assert first == [i.id for i in heldout.presentation_order(items)]
    assert first != [i.id for i in items]
    head = heldout.presentation_order(items)[:10]
    assert len({i.persona for i in head}) > 1


# -- labels file -------------------------------------------------------------

def test_label_round_trip_last_line_wins(tmp_path, items):
    path = tmp_path / "labels.jsonl"
    item = items[0]
    heldout.append_label(heldout.make_label(item, "S1", "O0", note="first"), path)
    heldout.append_label(heldout.make_label(item, Specificity.S2, Ownership.O1), path)
    labels = heldout.load_labels(path, items=items)
    assert labels[item.id].specificity is Specificity.S2
    assert labels[item.id].ownership is Ownership.O1
    assert labels[item.id].text_sha == item.text_sha
    assert len(path.read_text().splitlines()) == 2  # append-only


def test_label_for_unknown_item_is_rejected(tmp_path, items):
    path = tmp_path / "labels.jsonl"
    row = heldout.make_label(items[0], "S1", "O0").model_dump(mode="json")
    path.write_text(json.dumps({**row, "item_id": "ho-zzzzzz"}) + "\n")
    with pytest.raises(ValueError, match="unknown held-out item"):
        heldout.load_labels(path, items=items)


def test_text_drift_after_labelling_fails_loudly(tmp_path, items):
    path = tmp_path / "labels.jsonl"
    heldout.append_label(heldout.make_label(items[0], "S1", "O0"), path)
    edited = [items[0].model_copy(update={"text": items[0].text + " (edited)"}), *items[1:]]
    with pytest.raises(ValueError, match="held-out drift"):
        heldout.load_labels(path, items=edited)


@pytest.mark.parametrize("raw,want", [
    ("2 1", ("S2", "O1")), ("2/1", ("S2", "O1")), ("21", ("S2", "O1")),
    ("S3 O2", ("S3", "O2")), ("s0o0", ("S0", "O0")), ("2", None), ("4 1", None), ("2 3", None),
])
def test_parse_both(raw, want):
    got = label_heldout.parse_both(raw)
    assert (None if got is None else (got[0].value, got[1].value)) == want


def test_parse_single_axis():
    assert label_heldout.parse_specificity("S3") is Specificity.S3
    assert label_heldout.parse_specificity("3") is Specificity.S3
    assert label_heldout.parse_specificity("4") is None
    assert label_heldout.parse_ownership("o2") is Ownership.O2
    assert label_heldout.parse_ownership("3") is None


# -- interactive session -----------------------------------------------------

def test_session_records_skips_and_resumes(tmp_path, items):
    path = tmp_path / "labels.jsonl"
    order = heldout.presentation_order(items)
    out: list[str] = []
    script = _Script([
        "?", "2 1", "a note",          # item 1: rubric, then both axes at once
        "-",                           # item 2: skipped
        "3", "5", "o2", "",            # item 3: invalid ownership, then O2, no note
        "q",                           # item 4: quit
    ])
    assert label_heldout.run_session(ask=script, say=out.append, labels_path=path) == 0

    labels = heldout.load_labels(path, items=items)
    assert set(labels) == {order[0].id, order[2].id}
    assert (labels[order[0].id].specificity, labels[order[0].id].ownership) == (
        Specificity.S2, Ownership.O1)
    assert labels[order[0].id].note == "a note"
    assert (labels[order[2].id].specificity, labels[order[2].id].ownership) == (
        Specificity.S3, Ownership.O2)

    # Resume: the skipped item comes first, the labelled ones never come back.
    out2: list[str] = []
    label_heldout.run_session(ask=_Script(["q"]), say=out2.append, labels_path=path)
    text2 = "\n".join(out2)
    assert order[1].id in text2
    assert order[0].id not in text2 and order[2].id not in text2
    assert f"2 of {len(items)} labelled" in text2


def test_session_shows_question_answer_and_rubric_but_not_persona_or_topic(tmp_path, items):
    out: list[str] = []
    label_heldout.run_session(ask=_Script(["q"]), say=out.append,
                              labels_path=tmp_path / "labels.jsonl")
    text = "\n".join(out)
    first = heldout.presentation_order(items)[0]
    assert first.question.split()[0] in text and first.text.split()[0] in text
    assert "S3  An episode" in text and "O2  Says something new" in text
    for item in items:
        assert item.topic not in text
    for persona in PERSONAS:
        assert persona not in text.lower()


def test_session_with_limit_stops_and_says_how_to_continue(tmp_path, items):
    out: list[str] = []
    path = tmp_path / "labels.jsonl"
    label_heldout.run_session(1, ask=_Script(["1", "0", ""]), say=out.append, labels_path=path)
    assert len(heldout.load_labels(path, items=items)) == 1
    assert "make label-heldout" in "\n".join(out)


def test_session_treats_end_of_input_as_save_and_quit(tmp_path, items):
    path = tmp_path / "labels.jsonl"
    answers = iter(["2", "0"])

    def ask(prompt):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    out: list[str] = []
    assert label_heldout.run_session(ask=ask, say=out.append, labels_path=path) == 0
    labels = heldout.load_labels(path, items=items)
    assert len(labels) == 1  # the label given before Ctrl-D at the note prompt is kept
    assert "Saved 1 label" in "\n".join(out)


def test_session_with_nothing_left_says_so(tmp_path, items, intended):
    path = tmp_path / "labels.jsonl"
    _label(path, items, intended, len(items))
    out: list[str] = []
    label_heldout.run_session(ask=_Script([]), say=out.append, labels_path=path)
    assert "Nothing to label" in out[0]


# -- sheet export / import ---------------------------------------------------

def test_sheet_round_trip(tmp_path, items, intended):
    sheet, labels_path = tmp_path / "sheet.md", tmp_path / "labels.jsonl"
    path, count = label_heldout.export(sheet, labels_path=labels_path)
    assert count == len(items)
    text = sheet.read_text()
    order = heldout.presentation_order(items)
    assert text.index(order[0].id) < text.index(order[1].id) < text.index(order[2].id)
    # no proposal to accept: every S/O line is blank, and no author rationale leaks in
    assert re.findall(r"^S\[[^\]]+\]:[ \t]*\S", text, re.M) == []
    assert re.findall(r"^O\[[^\]]+\]:[ \t]*\S", text, re.M) == []
    # (one-word rationales such as "deflection" are rubric vocabulary, not a leak)
    assert not any(row["rationale"] in text for row in intended.values()
                   if len(row["rationale"].split()) >= 3)
    assert not any(row["pair"] in text for row in intended.values() if row["pair"])

    a, b, c, d, e = order[:5]
    text = (text.replace(f"S[{a.id}]:", f"S[{a.id}]: S2").replace(f"O[{a.id}]:", f"O[{a.id}]: O0")
                .replace(f"NOTE[{a.id}]:", f"NOTE[{a.id}]: thin but concrete")
                .replace(f"S[{b.id}]:", f"S[{b.id}]: 3").replace(f"O[{b.id}]:", f"O[{b.id}]: 1")
                .replace(f"S[{c.id}]:", f"S[{c.id}]: S1")                       # incomplete
                .replace(f"S[{d.id}]:", f"S[{d.id}]: S9").replace(f"O[{d.id}]:", f"O[{d.id}]: O0"))
    sheet.write_text(text)

    result = label_heldout.import_sheet(sheet, labels_path=labels_path)
    assert result["recorded"] == 2
    assert result["incomplete"] == 1 and result["invalid"] == 1
    assert result["blank"] == len(items) - 4
    assert (result["labelled"], result["of"]) == (2, len(items))
    labels = heldout.load_labels(labels_path, items=items)
    assert (labels[a.id].specificity, labels[a.id].ownership) == (Specificity.S2, Ownership.O0)
    assert labels[a.id].note == "thin but concrete" and labels[a.id].via == "sheet"
    assert (labels[b.id].specificity, labels[b.id].ownership) == (Specificity.S3, Ownership.O1)
    assert e.id not in labels

    again = label_heldout.import_sheet(sheet, labels_path=labels_path)
    assert again["recorded"] == 0 and again["already_labelled"] == 2
    assert len(labels_path.read_text().splitlines()) == 2

    _, remaining = label_heldout.export(sheet, labels_path=labels_path)
    assert remaining == len(items) - 2


def test_import_without_a_sheet_says_what_to_run(tmp_path):
    with pytest.raises(FileNotFoundError, match="label-heldout-export"):
        label_heldout.import_sheet(tmp_path / "missing.md", labels_path=tmp_path / "l.jsonl")


# -- the "n labelled" gate ---------------------------------------------------

class _MustNotRun:
    name = "must-not-run"

    def assess(self, text, prior):  # pragma: no cover - the point is it never runs
        raise AssertionError("an assessor ran below the labelling threshold")


def test_below_threshold_refuses_before_any_assessor_runs(tmp_path, items, intended):
    path = tmp_path / "labels.jsonl"
    _label(path, items, intended, heldout.MIN_LABELLED - 1)
    labels = heldout.load_labels(path, items=items)
    with pytest.raises(heldout.InsufficientLabels, match=f"only {heldout.MIN_LABELLED - 1} of"):
        heldout.evaluate_heldout(_MustNotRun(), items=items, labels=labels)

    built = []
    with pytest.raises(heldout.InsufficientLabels):
        heldout.run(["deterministic"], make=built.append, items=items, labels=labels)
    assert built == []  # refused before constructing anything


def test_at_threshold_scores_only_labelled_items_with_persona_clusters(tmp_path, items, intended):
    path = tmp_path / "labels.jsonl"
    chosen = _label(path, items, intended, heldout.MIN_LABELLED)
    labels = heldout.load_labels(path, items=items)
    result = heldout.evaluate_heldout(DeterministicAssessor(), items=items, labels=labels,
                                      n_boot=200)
    assert result["n"] == heldout.MIN_LABELLED and result["n_items"] == len(items)
    assert result["cluster_unit"] == "personas"
    assert result["clusters"] == len({i.persona for i in chosen})
    assert {r["id"] for r in result["rows"]} == {i.id for i in chosen}
    assert all("text" not in r for r in result["rows"])
    for metric in ("specificity_exact", "ownership_exact", "both_exact"):
        assert 0.0 <= result[metric] <= 1.0
        assert result[f"{metric}_k"] == result["clusters"]


def test_status_reports_n_labelled_of_n(tmp_path, items, intended):
    path = tmp_path / "labels.jsonl"
    _label(path, items, intended, 7)
    st = heldout.status(items, heldout.load_labels(path, items=items))
    assert (st["n_labelled"], st["n_items"]) == (7, len(items))
    assert sum(v["labelled"] for v in st["by_persona"].values()) == 7
    assert "7 labelled of" in heldout.format_status(st)


def test_author_agreement_is_perfect_when_labels_match_the_author(tmp_path, items, intended):
    path = tmp_path / "labels.jsonl"
    _label(path, items, intended, 30)
    agr = heldout.author_agreement(items, heldout.load_labels(path, items=items), intended,
                                   n_boot=200)
    assert agr["n"] == 30
    assert agr["both"]["rate"] == 1.0
    assert agr["both_on_boundary_items"]["n"] >= 1


def test_expand_assessor_specs():
    every = heldout.expand_assessor_specs("all")
    assert every[0] == "deterministic"
    assert len(every) == 1 + 2 * len(heldout.MODELS)
    assert heldout.expand_assessor_specs("deterministic, hybrid:haiku-4-5") == [
        "deterministic", "hybrid:haiku-4-5"]
    assert heldout.model_keys(every) == heldout.MODELS
    with pytest.raises(ValueError):
        heldout.expand_assessor_specs(" , ")


def test_a_failing_assessor_becomes_an_error_row(tmp_path, items, intended):
    path = tmp_path / "labels.jsonl"
    _label(path, items, intended, heldout.MIN_LABELLED)
    labels = heldout.load_labels(path, items=items)

    def make(spec):
        if spec == "deterministic":
            return DeterministicAssessor()
        raise RuntimeError("no credentials")

    rows = heldout.run(["deterministic", "llm:haiku-4-5"], make=make, items=items, labels=labels)
    assert "both_exact" in rows["deterministic"]
    assert rows["llm/haiku-4-5"] == {"error": "no credentials"}


# -- CLI ---------------------------------------------------------------------

def test_cli_refuses_below_threshold_and_records_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(heldout, "LABELS", tmp_path / "labels.jsonl")
    assert cli_main(["bench", "--assessors", "--split", "heldout"]) == 2
    err = capsys.readouterr().err
    assert "0 labelled of" in err and "no headline" in err
    results = tmp_path / "bench-results"
    assert not results.exists() or not any(results.iterdir())


def test_cli_scores_offline_and_records_without_item_text(tmp_path, monkeypatch, capsys,
                                                          items, intended):
    labels = tmp_path / "labels.jsonl"
    _label(labels, items, intended, 25)
    monkeypatch.setattr(heldout, "LABELS", labels)
    assert cli_main(["bench", "--assessors", "--split", "heldout", "--json",
                     "--note", "offline smoke"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"]["n_labelled"] == 25
    assert "both_exact" in payload["assessors"]["deterministic"]
    assert payload["author_agreement"]["n"] == 25

    results = tmp_path / "bench-results"
    md = next(results.glob("assessors-heldout-*.md")).read_text()
    assert "25 of" in md and "offline smoke" in md
    for item in items:
        assert item.text not in md
    assert "assessors-heldout" in (results / "HISTORY.md").read_text()


@pytest.mark.parametrize("argv", [
    ["bench", "--split", "heldout"],
    ["bench", "--assessors"],
    ["bench", "--assessors", "--split", "heldout", "--gate"],
])
def test_cli_rejects_mismatched_heldout_flags(argv):
    with pytest.raises(SystemExit):
        cli_main(argv)


def test_cli_label_heldout_export_and_import(tmp_path, monkeypatch, capsys, items):
    monkeypatch.setattr(heldout, "DIR", tmp_path)
    monkeypatch.setattr(heldout, "LABELS", tmp_path / "labels.jsonl")
    assert cli_main(["label", "--split", "heldout", "--export"]) == 0
    assert f"wrote {len(items)}" in capsys.readouterr().out
    sheet = tmp_path / label_heldout.SHEET_NAME
    first = heldout.presentation_order(items)[0]
    sheet.write_text(sheet.read_text()
                     .replace(f"S[{first.id}]:", f"S[{first.id}]: S1")
                     .replace(f"O[{first.id}]:", f"O[{first.id}]: O1"))
    assert cli_main(["label", "--split", "heldout", "--import"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["recorded"] == 1 and result["labelled"] == 1


def test_cli_label_heldout_rejects_disagreements_only():
    with pytest.raises(SystemExit):
        cli_main(["label", "--split", "heldout", "--disagreements-only"])
