"""Every transport is a thin wrapper over the same engine. These prove the seam
behaves identically however it is reached."""

import json

import pytest
from fastapi.testclient import TestClient

from convint.api.cli import main as cli_main
from convint.api.contract import CONTRACT_VERSION, Options, TurnRequest
from convint.api.http import build_app
from convint.api.mcp import TOOL_DECIDE_TURN, TOOL_GET_CONTRACT, TOOLS, handle_tool_call
from convint.domain import (
    ConversationState, InterviewPlan, StageSpec, TopicRecord, TopicSpec, Turn,
)

PLAN = InterviewPlan(
    plan_id="demo",
    stages=[StageSpec(stage_id="early_life", completion_signal="childhood_complete")],
    topics=[TopicSpec(topic_id="childhood", stage="early_life")],
)
STATE = ConversationState(
    turns=[Turn(role="assistant", content="What were you like as a kid?"),
           Turn(role="user", content="I helped at my parents' shop.")],
    topics=[TopicRecord(topic_id="childhood", stage="early_life")],
    current_topic_id="childhood",
)
REQUEST = TurnRequest(plan=PLAN, state=STATE, options=Options(generate_text=False))


@pytest.fixture
def client():
    return TestClient(build_app())


# --- HTTP ------------------------------------------------------------------

def test_health(client):
    assert client.get("/health").json()["contract_version"] == CONTRACT_VERSION


def test_contract_is_fetchable_by_consumers(client):
    body = client.get("/v1/contract").json()
    assert body["contract_version"] == CONTRACT_VERSION
    assert "properties" in body["request"]


def test_turn_over_http(client):
    body = client.post("/v1/turn", json=REQUEST.model_dump(mode="json")).json()
    assert body["decision"]["action"] == "follow_up"
    assert body["decision"]["rule_fired"] == "floor_not_met"


def test_major_version_mismatch_is_rejected(client):
    payload = REQUEST.model_dump(mode="json") | {"contract_version": "2.0"}
    resp = client.post("/v1/turn", json=payload)
    assert resp.status_code == 409


def test_minor_version_difference_is_accepted(client):
    payload = REQUEST.model_dump(mode="json") | {"contract_version": "1.7"}
    assert client.post("/v1/turn", json=payload).status_code == 200


def test_malformed_request_is_a_422_not_a_500(client):
    assert client.post("/v1/turn", json={"nonsense": True}).status_code == 422


# --- MCP -------------------------------------------------------------------

def test_mcp_advertises_both_tools():
    assert {t["name"] for t in TOOLS} == {TOOL_DECIDE_TURN, TOOL_GET_CONTRACT}


def test_mcp_tool_schema_is_the_contract():
    tool = next(t for t in TOOLS if t["name"] == TOOL_DECIDE_TURN)
    assert tool["inputSchema"] == TurnRequest.model_json_schema()


def test_mcp_dispatch_matches_http(client):
    over_mcp = handle_tool_call(TOOL_DECIDE_TURN, REQUEST.model_dump(mode="json"))
    over_http = client.post("/v1/turn", json=REQUEST.model_dump(mode="json")).json()
    assert over_mcp["decision"] == over_http["decision"]


def test_mcp_get_contract():
    assert handle_tool_call(TOOL_GET_CONTRACT, {})["contract_version"] == CONTRACT_VERSION


def test_unknown_mcp_tool_raises():
    with pytest.raises(ValueError, match="unknown tool"):
        handle_tool_call("nope", {})


# --- CLI -------------------------------------------------------------------

def test_cli_turn_from_file(tmp_path, capsys):
    path = tmp_path / "req.json"
    path.write_text(REQUEST.model_dump_json(), encoding="utf-8")
    assert cli_main(["turn", "--file", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["decision"]["rule_fired"] == "floor_not_met"


def test_cli_contract(capsys):
    assert cli_main(["contract"]) == 0
    assert json.loads(capsys.readouterr().out)["contract_version"] == CONTRACT_VERSION


def test_all_three_transports_agree(tmp_path, capsys, client):
    """The point of the architecture: same answer whichever seam you use."""
    path = tmp_path / "r.json"
    path.write_text(REQUEST.model_dump_json(), encoding="utf-8")
    cli_main(["turn", "--file", str(path)])
    via_cli = json.loads(capsys.readouterr().out)["decision"]
    via_http = client.post("/v1/turn", json=REQUEST.model_dump(mode="json")).json()["decision"]
    via_mcp = handle_tool_call(TOOL_DECIDE_TURN, REQUEST.model_dump(mode="json"))["decision"]
    assert via_cli == via_http == via_mcp
