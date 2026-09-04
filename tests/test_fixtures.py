"""Tier 2: the real corpus in docs/ must stay loadable and well-formed.

These run against this repository's own fixtures, so the component is testable
without the consumer application present.
"""

import collections

import pytest

from convint.domain import Specificity, assess_turn

ALLOWED_KEYS = {"name", "description", "userTurns", "paused", "openingMessage"}


def test_corpus_is_present(golden_files):
    assert len(golden_files) >= 11


def test_every_golden_matches_the_documented_shape(goldens):
    for stem, data in goldens.items():
        assert isinstance(data.get("name"), str) and data["name"], stem
        assert isinstance(data.get("description"), str) and data["description"], stem
        assert isinstance(data.get("userTurns"), list) and data["userTurns"], stem
        assert all(isinstance(t, str) for t in data["userTurns"]), stem


def test_no_unexpected_top_level_keys(goldens):
    """Guards against schema drift, e.g. a reintroduced `startingStep`."""
    for stem, data in goldens.items():
        assert set(data) <= ALLOWED_KEYS, f"{stem}: unexpected {set(data) - ALLOWED_KEYS}"


def test_name_matches_filename_stem(golden_files, goldens):
    for path in golden_files:
        assert goldens[path.stem]["name"] == path.stem


def test_description_carries_grading_intent(goldens):
    """`description` is the rubric, not a comment."""
    for stem, data in goldens.items():
        assert len(data["description"]) > 80, stem


def test_startingstep_is_absent_everywhere(goldens):
    assert not any("startingStep" in d for d in goldens.values())


# --- the extractor against real material ----------------------------------

def test_canonical_episode_from_the_real_corpus(goldens):
    """maya-full-walk turn 4 is the reference S3 episode."""
    turn = goldens["maya-full-walk"]["userTurns"][3]
    assert "furious about a dress" in turn
    assert assess_turn(turn).specificity is Specificity.S3


def test_thin_responder_deflection_from_the_real_corpus(goldens):
    turns = goldens["thin-responder-s1"]["userTurns"]
    deflection = next(t for t in turns if "don't really remember childhood" in t)
    assert assess_turn(deflection).specificity is Specificity.S0


def test_articulate_persona_outscores_thin_persona(goldens):
    """A sanity check on the extractor's discriminative power: the corpus was
    built so these two personas sit at opposite ends of the signal range."""
    def mean_rank(name):
        turns = goldens[name]["userTurns"]
        return sum(assess_turn(t).specificity.rank for t in turns) / len(turns)

    assert mean_rank("maya-full-walk") > mean_rank("thin-responder-s1")


def test_extractor_does_not_collapse_to_one_level(goldens):
    """If everything scores the same, the extractor is not measuring anything."""
    counts = collections.Counter(
        assess_turn(t).specificity
        for data in goldens.values()
        for t in data["userTurns"]
    )
    assert len(counts) >= 3, f"distribution too narrow: {counts}"


@pytest.mark.parametrize("persona", ["maya-s1", "rachel-s2", "grief-surfacing-s1"])
def test_every_persona_produces_some_gradable_material(goldens, persona):
    ranks = [assess_turn(t).specificity.rank for t in goldens[persona]["userTurns"]]
    assert max(ranks) >= Specificity.S2.rank
