from convint.domain import (
    ConversationState, InterviewPlan, Ownership, Specificity, StageSpec,
    TopicRecord, TopicSpec, artifact_readiness,
)

PLAN = InterviewPlan(
    plan_id="t",
    stages=[StageSpec(stage_id="early_life"), StageSpec(stage_id="career")],
    topics=[TopicSpec(topic_id="childhood", stage="early_life"),
            TopicSpec(topic_id="role", stage="career")],
)


def _ready_state():
    return ConversationState(
        topics=[
            TopicRecord(topic_id="childhood", stage="early_life",
                        specificity=Specificity.S3, ownership=Ownership.O1),
            TopicRecord(topic_id="role", stage="career",
                        specificity=Specificity.S2, ownership=Ownership.O1),
        ],
        coverage={"early_life": True, "career": True},
        pattern_confirmed=True,
    )


def test_fully_covered_conversation_is_ready():
    assert artifact_readiness(_ready_state(), PLAN).ready


def test_single_domain_is_not_a_disposition():
    """One domain is a job skill, not a pattern."""
    s = _ready_state()
    s.topics = [s.topics[0]]
    s.coverage = {"early_life": True, "career": True}
    r = artifact_readiness(s, PLAN)
    assert not r.ready and "single_domain_only" in r.missing


def test_no_episode_blocks_readiness():
    s = _ready_state()
    s.topics[0].specificity = Specificity.S2
    r = artifact_readiness(s, PLAN)
    assert "no_episode" in r.missing


def test_unconfirmed_pattern_blocks_readiness():
    s = _ready_state()
    s.pattern_confirmed = False
    assert "pattern_unconfirmed" in artifact_readiness(s, PLAN).missing


def test_confirmation_can_be_waived_by_plan():
    plan = PLAN.model_copy(update={"require_pattern_confirmation": False})
    s = _ready_state()
    s.pattern_confirmed = False
    assert artifact_readiness(s, plan).ready


def test_uncovered_required_stage_is_named():
    s = _ready_state()
    s.coverage["career"] = False
    assert "stage_not_covered:career" in artifact_readiness(s, PLAN).missing
