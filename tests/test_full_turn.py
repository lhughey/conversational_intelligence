"""Full-featured turns through every entry point, driven by fakes.

Covers: the question and the Read reaching HTTP, MCP and the CLI; the caller's
`assess` option; and the rule that a model failure degrades a turn (warning in
diagnostics) instead of failing it. No network.
"""

import json

import pytest
from fastapi.testclient import TestClient

from convint.adapters.assessor_hybrid import HybridAssessor
from convint.adapters.assessor_llm import LLMAssessor
from convint.adapters.llm_fake import FakeLLM
from convint.adapters.models import REGISTRY
from convint.api import mcp as mcp_api
from convint.api.cli import main as cli_main
from convint.api.contract import Options, TurnRequest
from convint.api.http import build_app
from convint.api.mcp import TOOL_DECIDE_TURN, handle_tool_call
from convint.app.metering import MeteredLLM
from convint.app.turn_engine import TurnEngine
from convint.domain import (
    Action, ConversationState, InterviewPlan, Ownership, Specificity, StageSpec,
    TopicRecord, TopicSpec, Turn, UserSignal,
)
from convint.domain.sufficiency import Assessment, SufficiencyComponents
from convint.ports.llm import LLMResponse, TruncatedResponse

QUESTION = "Which shop did you help at?"

# --- a follow-up turn (thin answer, floor not met) ---------------------------

FOLLOW_PLAN = InterviewPlan(
    plan_id="demo",
    stages=[StageSpec(stage_id="early_life", completion_signal="childhood_complete")],
    topics=[TopicSpec(topic_id="childhood", stage="early_life")],
)
FOLLOW_STATE = ConversationState(
    turns=[Turn(role="assistant", content="What were you like as a kid?"),
           Turn(role="user", content="I helped at my parents' shop.")],
    topics=[TopicRecord(topic_id="childhood", stage="early_life")],
    current_topic_id="childhood",
)

# --- a ready synthesize turn (closing signal, material supports a Read) ------

READ_PLAN = InterviewPlan(
    plan_id="t",
    stages=[StageSpec(stage_id="early_life"), StageSpec(stage_id="career")],
    topics=[TopicSpec(topic_id="childhood", stage="early_life"),
            TopicSpec(topic_id="role", stage="career")],
)
USER_TEXT = "I told my mom that. She comped the cleaning and the woman cried."
READ_STATE = ConversationState(
    turns=[Turn(role="user", content=USER_TEXT)],
    topics=[
        TopicRecord(topic_id="childhood", stage="early_life",
                    specificity=Specificity.S3, ownership=Ownership.O1),
        TopicRecord(topic_id="role", stage="career",
                    specificity=Specificity.S2, ownership=Ownership.O1),
    ],
    coverage={"early_life": True, "career": True},
    pattern_confirmed=True,
    signal=UserSignal.CLOSING,
)


def _read_json(**over):
    base = {"headline": "You find the real need", "changes": "Things clear up",
            "thrives": "Where terms are contested", "brings": "Translation"}
    return json.dumps(base | over)


def follow_request(**options) -> TurnRequest:
    return TurnRequest(plan=FOLLOW_PLAN, state=FOLLOW_STATE, options=Options(**options))


def read_request(**options) -> TurnRequest:
    return TurnRequest(plan=READ_PLAN, state=READ_STATE, options=Options(**options))


class StubModelAssessor:
    """Stands in for a model-backed assessor; records whether it was asked."""

    name = "llm/stub"

    def __init__(self, raises: Exception | None = None):
        self.raises = raises
        self.calls = 0

    def assess(self, text, prior):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return Assessment(specificity=Specificity.S2, ownership=Ownership.O0,
                          components=SufficiencyComponents(), assessor=self.name)


class Failing:
    """An LLM adapter whose every call fails like a provider would."""

    name = "failing"

    def __init__(self, exc: Exception):
        self.exc = exc

    def complete(self, request):
        raise self.exc


class Billed(FakeLLM):
    """FakeLLM that reports token usage, for cost accounting."""

    def __init__(self, usage, **kw):
        super().__init__(**kw)
        self.usage = usage

    def complete(self, request):
        r = super().complete(request)
        return LLMResponse(text=r.text, model="claude-haiku-4-5", usage=dict(self.usage))


# --- the question and the Read reach every transport -------------------------

@pytest.fixture
def question_engine():
    return TurnEngine(llm=FakeLLM(default=QUESTION))


@pytest.fixture
def read_engine():
    return TurnEngine(llm=FakeLLM(default=_read_json()))


def _cli(engine, request, monkeypatch, capsys, tmp_path, *flags):
    seen = {}

    def fake_build_engine(**kwargs):
        seen.update(kwargs)
        return engine

    monkeypatch.setattr("convint.app.engine_factory.build_engine", fake_build_engine)
    path = tmp_path / "req.json"
    path.write_text(request.model_dump_json(), encoding="utf-8")
    assert cli_main(["turn", "--file", str(path), *flags]) == 0
    return json.loads(capsys.readouterr().out), seen


def test_http_returns_the_question(question_engine):
    body = TestClient(build_app(question_engine)).post(
        "/v1/turn", json=follow_request().model_dump(mode="json")).json()
    assert body["decision"]["action"] == "follow_up"
    assert body["message"]["text"] == QUESTION
    assert body["diagnostics"]["model"] == "fake"


def test_http_returns_the_read(read_engine):
    body = TestClient(build_app(read_engine)).post(
        "/v1/turn", json=read_request().model_dump(mode="json")).json()
    assert body["decision"]["action"] == "synthesize"
    assert body["artifact"]["headline"] == "You find the real need"
    assert body["artifact"]["readiness"]["ready"] is True


def test_mcp_returns_the_question_and_the_read(question_engine, read_engine):
    out = handle_tool_call(TOOL_DECIDE_TURN, follow_request().model_dump(mode="json"),
                           engine=question_engine)
    assert out["message"]["text"] == QUESTION
    out = handle_tool_call(TOOL_DECIDE_TURN, read_request().model_dump(mode="json"),
                           engine=read_engine)
    assert out["artifact"]["headline"] == "You find the real need"


def test_cli_returns_the_question_and_the_read(
    question_engine, read_engine, monkeypatch, capsys, tmp_path
):
    out, _ = _cli(question_engine, follow_request(), monkeypatch, capsys, tmp_path)
    assert out["message"]["text"] == QUESTION
    out, _ = _cli(read_engine, read_request(), monkeypatch, capsys, tmp_path)
    assert out["artifact"]["headline"] == "You find the real need"


def test_cli_passes_model_flags_to_the_factory(question_engine, monkeypatch, capsys, tmp_path):
    _, seen = _cli(question_engine, follow_request(), monkeypatch, capsys, tmp_path,
                   "--assessor", "llm:sonnet-5", "--model", "none")
    assert seen == {"assessor": "llm:sonnet-5", "model": "none"}


def test_transports_agree_on_a_full_turn(question_engine, monkeypatch, capsys, tmp_path):
    req = follow_request()
    via_http = TestClient(build_app(question_engine)).post(
        "/v1/turn", json=req.model_dump(mode="json")).json()
    via_mcp = handle_tool_call(TOOL_DECIDE_TURN, req.model_dump(mode="json"),
                               engine=question_engine)
    via_cli, _ = _cli(question_engine, req, monkeypatch, capsys, tmp_path)
    for key in ("decision", "message", "state_delta"):
        assert via_http[key] == via_mcp[key] == via_cli[key]


def test_default_transports_use_the_configured_engine():
    """conftest pins CONVINT_ASSESSOR=deterministic / CONVINT_MODEL=none, so a
    default-built server is model-free here."""
    body = TestClient(build_app()).post(
        "/v1/turn", json=follow_request().model_dump(mode="json")).json()
    assert body["message"] is None
    assert body["diagnostics"]["assessor"] == "deterministic"
    assert body["diagnostics"]["degraded"] is False


def test_mcp_builds_its_engine_once(monkeypatch):
    built = []

    def fake_build_engine(**kwargs):
        built.append(kwargs)
        return TurnEngine()

    monkeypatch.setattr("convint.app.engine_factory.build_engine", fake_build_engine)
    monkeypatch.setattr(mcp_api, "_engine", None)
    for _ in range(3):
        handle_tool_call(TOOL_DECIDE_TURN, follow_request().model_dump(mode="json"))
    assert len(built) == 1


def test_mcp_tool_description_mentions_the_question_and_the_read():
    tool = next(t for t in mcp_api.TOOLS if t["name"] == TOOL_DECIDE_TURN)
    assert "next question" in tool["description"] and "Read" in tool["description"]


# --- the caller's `assess` option ----------------------------------------------

def test_assess_defaults_to_server():
    assert Options().assess == "server"


def test_assess_server_uses_the_configured_assessor():
    stub = StubModelAssessor()
    resp = TurnEngine(assessor=stub, assessor_model="claude-x").run(follow_request())
    assert stub.calls == 1
    assert resp.diagnostics.assessor == "llm/stub"
    assert resp.diagnostics.assessor_model == "claude-x"
    assert resp.diagnostics.warnings == []


def test_assess_deterministic_bypasses_the_model():
    stub = StubModelAssessor()
    resp = TurnEngine(assessor=stub, assessor_model="claude-x").run(
        follow_request(assess="deterministic"))
    assert stub.calls == 0
    assert resp.diagnostics.assessor == "deterministic"
    assert resp.diagnostics.assessor_model is None
    assert resp.diagnostics.degraded is False


def test_assess_llm_uses_the_model_backed_assessor():
    stub = StubModelAssessor()
    resp = TurnEngine(assessor=stub).run(follow_request(assess="llm"))
    assert stub.calls == 1 and resp.diagnostics.warnings == []


def test_assess_llm_without_a_model_falls_back_with_a_warning():
    resp = TurnEngine().run(follow_request(assess="llm"))
    assert resp.diagnostics.assessor == "deterministic"
    assert resp.diagnostics.warnings[0].startswith("assess_llm_unavailable")
    assert resp.diagnostics.degraded is True


def test_invalid_assess_value_is_a_422():
    payload = follow_request().model_dump(mode="json")
    payload["options"]["assess"] = "gpt-4.1"
    assert TestClient(build_app(TurnEngine())).post("/v1/turn", json=payload).status_code == 422


# --- a model failure never fails a turn ----------------------------------------

@pytest.mark.parametrize("exc", [
    TruncatedResponse("cut off", usage={"input": 5, "output": 400}),
    RuntimeError("APIConnectionError: connection refused"),
    ValueError("assessor returned unparseable output"),
])
def test_assessor_failure_falls_back_to_deterministic(exc):
    stub = StubModelAssessor(raises=exc)
    resp = TurnEngine(assessor=stub).run(follow_request(generate_text=False))
    assert resp.decision.action is Action.FOLLOW_UP
    assert resp.assessment.assessor == "deterministic"
    assert resp.diagnostics.assessor == "deterministic"
    assert resp.diagnostics.warnings == [f"assessor_fallback: {type(exc).__name__}: {exc}"]
    assert resp.diagnostics.degraded is True


def test_real_llm_assessor_with_garbage_output_falls_back():
    """The actual model path: LLMAssessor over a fake that returns non-JSON."""
    assessor = HybridAssessor(LLMAssessor(FakeLLM(default="not json")))
    resp = TurnEngine(assessor=assessor).run(follow_request(generate_text=False))
    assert resp.diagnostics.assessor == "deterministic"
    assert resp.diagnostics.warnings[0].startswith("assessor_fallback: ValueError")


def test_deterministic_assessor_errors_are_not_swallowed():
    """The catch is scoped to the model path; a bug in the rules propagates."""
    engine = TurnEngine()

    def boom(text, prior):
        raise ZeroDivisionError("bug")

    engine.fallback_assessor.assess = boom
    with pytest.raises(ZeroDivisionError):
        engine.run(follow_request(generate_text=False))


def test_generation_failure_returns_no_message_but_advances_bookkeeping():
    engine = TurnEngine(llm=Failing(RuntimeError("overloaded")))
    resp = engine.run(follow_request())
    assert resp.decision.action is Action.FOLLOW_UP
    assert resp.message is None
    topic = resp.state_delta.topics[0]
    assert topic.followups_used == 1 and topic.asked_questions == []
    assert resp.diagnostics.warnings == ["generation_failed: RuntimeError: overloaded"]
    assert resp.diagnostics.degraded is True


def test_truth_floor_violation_withholds_the_read():
    engine = TurnEngine(llm=FakeLLM(default=_read_json(headline='You "scaled a 400-person org"')))
    resp = engine.run(read_request())
    assert resp.decision.action is Action.SYNTHESIZE
    assert resp.artifact is None
    assert resp.readiness.ready is True
    assert resp.diagnostics.warnings[0].startswith("artifact_withheld: TruthFloorViolation")
    assert resp.diagnostics.degraded is True


def test_invented_number_withholds_the_read():
    """Unquoted invented specifics are held to the same hard floor as quotes."""
    engine = TurnEngine(llm=FakeLLM(default=_read_json(brings="You grew revenue by 300%")))
    resp = engine.run(read_request())
    assert resp.artifact is None and resp.readiness.ready is True
    assert "numbers not found in the user's own words: ['300%']" in resp.diagnostics.warnings[0]


def test_artifact_provider_error_withholds_the_read():
    resp = TurnEngine(llm=Failing(RuntimeError("500"))).run(read_request())
    assert resp.artifact is None and resp.readiness.ready is True
    assert resp.diagnostics.warnings == ["artifact_withheld: RuntimeError: 500"]


def test_long_error_messages_are_shortened():
    resp = TurnEngine(llm=Failing(RuntimeError("x" * 1000 + "\nsecond line"))).run(
        follow_request())
    assert len(resp.diagnostics.warnings[0]) < 260


# --- usage and cost --------------------------------------------------------------

def test_usage_and_cost_sum_over_assessor_and_generation():
    spec = REGISTRY["haiku-4-5"]
    assessor_json = json.dumps({
        "specificity": "S1", "ownership": "O0", "scene": False, "stakes": False,
        "action": False, "outcome": False, "reflection": False, "evidence": "",
    })
    assessor = HybridAssessor(LLMAssessor(MeteredLLM(
        Billed({"input": 1000, "output": 100}, default=assessor_json), spec=spec)))
    llm = MeteredLLM(Billed({"input": 2000, "output": 50}, default=QUESTION), spec=spec)
    resp = TurnEngine(assessor=assessor, llm=llm, assessor_model=spec.model_id).run(
        follow_request())
    diag = resp.diagnostics
    assert diag.usage == {"input": 3000, "output": 150}
    assert diag.cost_usd == pytest.approx(3000 / 1e6 * 1.0 + 150 / 1e6 * 5.0)
    assert diag.model == "claude-haiku-4-5" and diag.assessor_model == "claude-haiku-4-5"


def test_cost_is_unknown_for_an_unpriced_model_and_zero_without_calls():
    assert TurnEngine(llm=FakeLLM(default=QUESTION)).run(
        follow_request()).diagnostics.cost_usd is None
    assert TurnEngine().run(follow_request()).diagnostics.cost_usd == 0.0


def test_usage_of_a_truncated_call_is_still_counted():
    spec = REGISTRY["haiku-4-5"]
    exc = TruncatedResponse("cut", usage={"input": 10, "output": 300})
    resp = TurnEngine(llm=MeteredLLM(Failing(exc), spec=spec)).run(follow_request())
    assert resp.diagnostics.usage == {"input": 10, "output": 300}
    assert resp.diagnostics.warnings[0].startswith("generation_failed: TruncatedResponse")
