"""Persona banks and the balanced set generated from them."""

import pytest

from convint.bench import gate_eval
from convint.dataset.bank import Persona, load_personas
from convint.dataset.synth import (
    BUDGET_STATES, build_from_banks, minimal_pairs, spec_action,
)
from convint.domain.enums import Action, Ownership, Specificity
from convint.domain.gate import decide


def test_banks_load():
    personas = load_personas()
    assert personas and all(isinstance(p, Persona) for p in personas)


def test_every_rung_declares_its_own_sufficiency():
    """The point of a bank: gold sufficiency is authored, not inferred, so the
    weak-label problem does not exist on this axis."""
    for persona in load_personas():
        for topic in persona.topics:
            assert topic.rungs
            for rung in topic.rungs:
                assert isinstance(rung.specificity, Specificity)
                assert isinstance(rung.ownership, Ownership)


def test_rungs_withhold_depth():
    """An episode must not be servable before its setup, or 'draw it out — do
    not hand it over' is unmeasurable and antecedents dangle."""
    for persona in load_personas():
        for topic in persona.topics:
            episode = topic.rung("S3")
            if episode is not None:
                assert episode.requires_prior, f"{topic.topic_id} S3 has no prerequisite"


def test_requires_prior_references_a_real_rung():
    for persona in load_personas():
        for topic in persona.topics:
            names = {r.rung for r in topic.rungs}
            for rung in topic.rungs:
                assert set(rung.requires_prior) <= names, topic.topic_id


def test_bank_covers_the_corpus_gap():
    """No golden transcript supplies environment or drain material, which made
    `thrives` unreachable. The bank fills it."""
    stages = {t.stage for p in load_personas() for t in p.topics}
    assert "thrives" in stages


# --- generated set ---------------------------------------------------------

def test_generated_set_is_balanced():
    """The corpus was 72/20 follow-up; a set that skewed cannot distinguish a
    good gate from a policy that never advances."""
    _, labels = build_from_banks()
    counts = {a: sum(1 for l in labels if l.action is a) for a in
              (Action.FOLLOW_UP, Action.ADVANCE)}
    minority = min(counts.values()) / sum(counts.values())
    assert minority > 0.3, counts


def test_every_budget_state_is_exercised():
    items, _ = build_from_banks()
    assert {i.followups_used for i in items} == set(BUDGET_STATES)


def test_minimal_pairs_exist_and_differ_only_in_the_rung():
    items, labels = build_from_banks()
    pairs = minimal_pairs(items, labels)
    assert len(pairs) >= 8
    by_id = {i.item_id: i for i in items}
    for a, b in pairs:
        assert by_id[a].followups_used == by_id[b].followups_used
        assert a.split("#")[0] == b.split("#")[0]


def test_spec_and_implementation_agree():
    """`spec_action` is written independently of gate.py. Agreement is a real
    conformance property; sharing one function would make this vacuous."""
    items, _ = build_from_banks()
    for item in items:
        expected, _ = spec_action(
            item.specificity, item.ownership, item.followups_used, item.floor, item.ceiling
        )
        assert gate_eval.gate_policy(item) is expected, item.item_id


# --- the diagnostic that matters -------------------------------------------

def test_minimal_pairs_expose_a_policy_that_ignores_content():
    """budget_only looks accurate (88%) yet scores 0% on minimal pairs, because
    it reads the turn counter and never the answer. This is precisely the
    failure the whole component exists to prevent, and accuracy alone hides it."""
    result = gate_eval.run("synth")
    assert result["budget_only"]["accuracy_strict"] > 0.8
    assert result["budget_only"]["minimal_pair_accuracy"] == 0.0
    assert result["gate"]["minimal_pair_accuracy"] == 1.0


def test_balanced_split_has_real_denominators_for_both_failures():
    result = gate_eval.run("synth")["gate"]
    assert result["premature_advance_n"] >= 20
    assert result["stall_n"] >= 10   # the corpus split had 2
