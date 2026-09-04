"""Tier 2: the seam. If these fail, a consumer breaks."""

import json
import pathlib
import subprocess
import sys

from convint.api.contract import (
    CONTRACT_VERSION, Options, TurnRequest, TurnResponse,
)
from convint.domain import (
    Action, ConversationState, Decision, InterviewPlan, Ownership, Specificity,
    StageSpec, SubAction, TopicSpec, Assessment, artifact_readiness,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
CONTRACTS = REPO / "contracts" / "v1"

PLAN = InterviewPlan(
    plan_id="t", stages=[StageSpec(stage_id="early_life")],
    topics=[TopicSpec(topic_id="childhood", stage="early_life")],
)


def test_committed_schema_matches_the_models():
    """Schema drift fails here rather than in a consumer."""
    for filename, model in (
        ("turn-request.schema.json", TurnRequest),
        ("turn-response.schema.json", TurnResponse),
    ):
        committed = json.loads((CONTRACTS / filename).read_text())
        assert committed == model.model_json_schema(), (
            f"{filename} is stale — run: python scripts/export_contracts.py"
        )


def test_export_script_is_idempotent():
    before = {p.name: p.read_text() for p in CONTRACTS.glob("*.json")}
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "export_contracts.py")],
        check=True, capture_output=True,
    )
    after = {p.name: p.read_text() for p in CONTRACTS.glob("*.json")}
    assert before == after


def test_request_round_trips_through_json():
    req = TurnRequest(plan=PLAN, state=ConversationState(), options=Options())
    assert TurnRequest.model_validate_json(req.model_dump_json()) == req


def test_response_round_trips_through_json():
    state = ConversationState()
    resp = TurnResponse(
        decision=Decision(
            action=Action.FOLLOW_UP, sub_action=SubAction.DEEPEN,
            rule_fired="default_deepen", rationale="because",
        ),
        assessment=Assessment(specificity=Specificity.S1, ownership=Ownership.O0),
        readiness=artifact_readiness(state, PLAN),
    )
    assert TurnResponse.model_validate_json(resp.model_dump_json()) == resp


def test_version_is_stamped_by_default():
    assert TurnRequest(plan=PLAN, state=ConversationState()).contract_version == CONTRACT_VERSION


def test_message_is_nullable_so_callers_can_write_their_own_words():
    """The escape hatch that keeps voice ownership with the consumer."""
    assert "message" in TurnResponse.model_json_schema()["properties"]
    resp = TurnResponse(
        decision=Decision(action=Action.ADVANCE, sub_action=SubAction.HANDOFF,
                          rule_fired="gate_met", rationale="r"),
        assessment=Assessment(specificity=Specificity.S3, ownership=Ownership.O1),
        readiness=artifact_readiness(ConversationState(), PLAN),
        message=None,
    )
    assert resp.message is None


def test_enum_values_are_stable_strings():
    """These are contract values; renaming one is a breaking change."""
    assert {a.value for a in Action} == {
        "follow_up", "advance", "synthesize", "refuse_and_continue"
    }
    assert {s.value for s in Specificity} == {"S0", "S1", "S2", "S3"}
    assert {o.value for o in Ownership} == {"O0", "O1", "O2"}
