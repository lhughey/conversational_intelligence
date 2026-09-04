"""The gate rule table. These tests are the specification."""

import pytest

from convint.domain import (
    Action, Budget, ConversationState, InterviewPlan, Ownership, Specificity,
    StageSpec, SubAction, TopicRecord, TopicSpec, Turn, UserSignal, decide,
)

PLAN = InterviewPlan(
    plan_id="test",
    stages=[
        StageSpec(stage_id="early_life", completion_signal="childhood_complete"),
        StageSpec(stage_id="career", completion_signal="career_complete"),
    ],
    topics=[
        TopicSpec(topic_id="childhood", stage="early_life"),
        TopicSpec(topic_id="role", stage="career"),
    ],
    default_budget=Budget(floor=1, ceiling=3),
)


def state(spec=Specificity.S1, own=Ownership.O0, used=1, signal=UserSignal.NONE, **kw):
    return ConversationState(
        turns=[Turn(role="user", content="...")],
        topics=[TopicRecord(
            topic_id="childhood", stage="early_life",
            followups_used=used, specificity=spec, ownership=own,
        )],
        current_topic_id="childhood",
        signal=signal,
        **kw,
    )


# --- signal overrides ------------------------------------------------------

def test_adversarial_never_advances():
    d = decide(state(signal=UserSignal.ADVERSARIAL), PLAN)
    assert d.action is Action.REFUSE_AND_CONTINUE
    assert d.rule_fired == "adversarial_input"


def test_distress_holds_and_defers_safety_to_caller():
    d = decide(state(signal=UserSignal.DISTRESS), PLAN)
    assert (d.action, d.sub_action) == (Action.FOLLOW_UP, SubAction.HOLD)


def test_topic_change_outranks_sufficiency():
    """User volunteering new material beats the depth bar, even at S0."""
    d = decide(state(spec=Specificity.S0, used=0, signal=UserSignal.TOPIC_CHANGE), PLAN)
    assert d.action is Action.ADVANCE
    assert d.rule_fired == "topic_change_outranks_sufficiency"


def test_impatience_does_not_override_the_gate():
    """The failure `tries-to-rush` exists to catch: pressure is not sufficiency."""
    d = decide(state(spec=Specificity.S1, own=Ownership.O1, signal=UserSignal.IMPATIENT), PLAN)
    assert d.action is Action.FOLLOW_UP


def test_impatience_and_closing_are_different():
    impatient = decide(state(signal=UserSignal.IMPATIENT), PLAN)
    closing = decide(state(signal=UserSignal.CLOSING), PLAN)
    assert impatient.action is Action.FOLLOW_UP
    assert closing.action is Action.SYNTHESIZE


def test_closing_without_coverage_is_an_honest_shortfall():
    d = decide(state(signal=UserSignal.CLOSING), PLAN)
    assert d.action is Action.SYNTHESIZE
    assert d.rule_fired == "closing_honest_shortfall"
    assert "Missing" in d.rationale


def test_acknowledgment_only_is_a_signpost_not_material():
    d = decide(state(signal=UserSignal.ACKNOWLEDGMENT_ONLY), PLAN)
    assert d.action is Action.ADVANCE
    assert d.completion_signal == "childhood_complete"


# --- budget ----------------------------------------------------------------

def test_floor_blocks_advance_even_when_material_is_rich():
    """Floor AND gate must both hold: 'hitting the floor without surfacing
    wiring is NOT a green light', and neither is the reverse."""
    d = decide(state(spec=Specificity.S3, own=Ownership.O2, used=0), PLAN)
    assert d.action is Action.FOLLOW_UP
    assert d.rule_fired == "floor_not_met"


def test_ceiling_forces_advance_even_when_material_is_thin():
    """A floor with no ceiling is interrogation."""
    d = decide(state(spec=Specificity.S0, used=3), PLAN)
    assert d.action is Action.ADVANCE
    assert d.rule_fired == "ceiling_reached"


def test_ceiling_outranks_floor_when_they_conflict():
    plan = InterviewPlan(
        plan_id="x", stages=[StageSpec(stage_id="early_life")],
        topics=[TopicSpec(topic_id="childhood", stage="early_life",
                          budget=Budget(floor=2, ceiling=2))],
    )
    d = decide(state(spec=Specificity.S0, used=2), plan)
    assert d.rule_fired == "ceiling_reached"


# --- sufficiency gate ------------------------------------------------------

@pytest.mark.parametrize(
    "spec,own,expected",
    [
        (Specificity.S3, Ownership.O1, Action.ADVANCE),   # episode + owned
        (Specificity.S3, Ownership.O2, Action.ADVANCE),
        (Specificity.S2, Ownership.O2, Action.ADVANCE),   # they did the work
        (Specificity.S3, Ownership.O0, Action.FOLLOW_UP),  # episode, unowned
        (Specificity.S2, Ownership.O1, Action.FOLLOW_UP),
        (Specificity.S1, Ownership.O2, Action.FOLLOW_UP),  # insight, no material
        (Specificity.S0, Ownership.O0, Action.FOLLOW_UP),
    ],
)
def test_gate_truth_table(spec, own, expected):
    assert decide(state(spec=spec, own=own, used=1), PLAN).action is expected


def test_s0_redirects_rather_than_deepening():
    """A thin answer gets a smaller question elsewhere, not more of the same."""
    d = decide(state(spec=Specificity.S0, used=1), PLAN)
    assert (d.action, d.sub_action) == (Action.FOLLOW_UP, SubAction.REDIRECT)


def test_s0_under_floor_also_redirects():
    d = decide(state(spec=Specificity.S0, used=0), PLAN)
    assert d.sub_action is SubAction.REDIRECT


# --- invariants ------------------------------------------------------------

def test_every_decision_is_attributable():
    """An unattributable decision is a bug, not a mystery."""
    for signal in UserSignal:
        for spec in Specificity:
            for own in Ownership:
                for used in (0, 1, 3):
                    d = decide(state(spec=spec, own=own, used=used, signal=signal), PLAN)
                    assert d.rule_fired, "rule_fired must never be empty"
                    assert d.rationale


def test_no_active_topic_is_handled():
    s = ConversationState(current_topic_id=None)
    assert decide(s, PLAN).rule_fired == "no_active_topic"


def test_gate_is_pure_and_does_not_mutate_state():
    s = state(spec=Specificity.S3, own=Ownership.O2, used=2)
    before = s.model_dump_json()
    decide(s, PLAN)
    assert s.model_dump_json() == before
