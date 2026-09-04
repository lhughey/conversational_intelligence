"""The benchmark must run offline and must fail loudly on fixture drift."""

import json

import pytest

from convint.adapters.assessor_deterministic import DeterministicAssessor
from convint.api.cli import main as cli_main
from convint.bench import corpus
from convint.bench.evaluate import evaluate, load_labels


def test_seed_labels_load_and_are_well_formed():
    labels = load_labels()
    assert len(labels) >= 20
    for row in labels:
        assert row["specificity"] in {"S0", "S1", "S2", "S3"}
        assert row["ownership"] in {"O0", "O1", "O2"}
        assert row["note"] and row["text_prefix"]


def test_deterministic_assessor_beats_chance_by_a_wide_margin():
    """A floor, not a leaderboard. Chance on 4 classes is 25%."""
    result = evaluate(DeterministicAssessor())
    assert result["specificity_exact"] > 0.6
    assert result["ownership_exact"] > 0.6


def test_ordinal_error_is_never_more_than_one_level():
    """The scale is ordinal; a two-level miss would mean it is not measuring
    the thing it claims to measure."""
    assert evaluate(DeterministicAssessor())["specificity_within_1"] == 1.0


def test_fixture_drift_fails_loudly():
    """If a transcript changes, labels must be redone - never silently re-scored."""
    labels = load_labels()
    labels[0] = {**labels[0], "text_prefix": "this text is not in the corpus"}
    with pytest.raises(ValueError, match="fixture drift"):
        evaluate(DeterministicAssessor(), labels)


def test_corpus_replay_covers_every_transcript():
    result = corpus.run()
    assert result["transcripts"] >= 11
    assert result["turns"] >= 90


def test_corpus_replay_exercises_more_than_one_rule():
    """A single rule firing everywhere would mean the gate is not discriminating."""
    assert len(corpus.run()["rules"]) >= 3


def test_bench_cli_emits_json(capsys):
    assert cli_main(["bench", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["agreement"]["n"] >= 20
    assert payload["corpus"]["transcripts"] >= 11
