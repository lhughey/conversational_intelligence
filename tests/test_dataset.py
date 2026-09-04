"""The turn-decision dataset and its evaluation."""

import pytest

from convint.bench import gate_eval
from convint.dataset.build import build, load
from convint.dataset.schema import Item, Label
from convint.domain.enums import Action


def test_build_produces_one_item_per_user_turn():
    items, labels = build()
    assert len(items) == len(labels) >= 90
    assert all(i.item_id == l.item_id for i, l in zip(items, labels))


def test_items_carry_the_state_the_gate_needs():
    items, _ = build()
    probe = items[0]
    for field in ("followups_used", "floor", "ceiling", "specificity", "ownership", "signal"):
        assert hasattr(probe, field)


def test_every_label_is_marked_weak():
    """No number from this set may be quoted as an accuracy without adjudication."""
    _, labels = build()
    assert {l.source for l in labels} == {"weak"}


def test_committed_dataset_matches_a_fresh_build():
    """Regenerating must be deterministic, or the committed file is a fiction."""
    built_items, built_labels = build()
    loaded_items, loaded_labels = load()
    assert [i.item_id for i in built_items] == [i.item_id for i in loaded_items]
    assert [l.action for l in built_labels] == [l.action for l in loaded_labels]


def test_labels_cover_every_action_kind():
    _, labels = build()
    assert {l.action for l in labels} >= {
        Action.FOLLOW_UP, Action.ADVANCE, Action.SYNTHESIZE, Action.REFUSE_AND_CONTINUE
    }


def test_acceptable_set_scoring():
    label = Label(item_id="x", action=Action.FOLLOW_UP, acceptable=[Action.ADVANCE])
    assert label.is_correct(Action.FOLLOW_UP)
    assert label.is_correct(Action.ADVANCE)
    assert not label.is_correct(Action.SYNTHESIZE)


def test_text_prefix_guards_against_fixture_drift():
    items, _ = build()
    assert all(i.text.startswith(i.text_prefix) for i in items)


# --- gate evaluation -------------------------------------------------------

def test_gate_eval_reports_both_failure_directions():
    result = gate_eval.run()
    for name, metrics in result.items():
        assert metrics["premature_advance_rate"] is not None, name
        assert metrics["stall_rate"] is not None, name


def test_degenerate_policies_are_exposed_by_the_metric_pair():
    """Neither failure rate means anything alone; together they catch both
    ways of gaming the benchmark."""
    result = gate_eval.run()
    assert result["always_follow_up"]["premature_advance_rate"] == 0.0
    assert result["always_follow_up"]["stall_rate"] == 1.0
    assert result["always_advance"]["premature_advance_rate"] == 1.0
    assert result["always_advance"]["stall_rate"] == 0.0


def test_gate_is_not_a_degenerate_policy():
    """The whole point: the gate must sit between the two extremes rather than
    collapsing onto one of them."""
    gate = gate_eval.run()["gate"]
    assert 0.0 < gate["premature_advance_rate"] < 1.0
    assert gate["accuracy_acceptable"] > 0.8


def test_denominators_are_reported_so_small_n_is_visible():
    result = gate_eval.run()["gate"]
    assert result["premature_advance_n"] > 0
    assert result["stall_n"] > 0
