import pytest
from pydantic import ValidationError

from convint.domain import Budget, InterviewPlan, StageSpec, TopicSpec


def _plan(**kw):
    base = dict(
        plan_id="p",
        stages=[StageSpec(stage_id="early_life", completion_signal="childhood_complete")],
        topics=[TopicSpec(topic_id="a", stage="early_life")],
    )
    base.update(kw)
    return InterviewPlan(**base)


def test_ceiling_below_floor_is_rejected():
    with pytest.raises(ValidationError):
        Budget(floor=3, ceiling=1)


def test_floor_equal_to_ceiling_is_allowed():
    assert Budget(floor=2, ceiling=2).ceiling == 2


def test_topic_referencing_unknown_stage_is_rejected():
    with pytest.raises(ValidationError):
        InterviewPlan(plan_id="p", stages=[], topics=[TopicSpec(topic_id="a", stage="ghost")])


def test_per_topic_budget_overrides_default():
    plan = _plan(
        default_budget=Budget(floor=1, ceiling=3),
        topics=[TopicSpec(topic_id="a", stage="early_life", budget=Budget(floor=2, ceiling=5))],
    )
    assert plan.budget_for("a").floor == 2
    assert plan.budget_for("unknown").floor == 1  # falls back to the default


def test_completion_signal_is_opaque_passthrough():
    """The core must not interpret consumer tool names."""
    assert _plan().stage("early_life").completion_signal == "childhood_complete"
