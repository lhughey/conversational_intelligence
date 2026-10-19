"""The crisis screen in a full turn: it holds the interview and is reported as
`diagnostics.safety` (contract 1.3). Synthetic text, no model, no network."""

import pytest
from fastapi.testclient import TestClient

from convint.api.contract import Options, TurnRequest
from convint.api.http import build_app
from convint.app.turn_engine import TurnEngine
from convint.domain import (
    Action, ConversationState, InterviewPlan, StageSpec, SubAction, TopicRecord, TopicSpec, Turn,
    UserSignal,
)
from convint.domain.crisis import PATTERNS_VERSION, SCREENER

PLAN = InterviewPlan(plan_id="p", stages=[StageSpec(stage_id="s")],
                     topics=[TopicSpec(topic_id="t", stage="s")])


def request(user_text: str | None, signal=UserSignal.NONE, **options) -> TurnRequest:
    turns = [Turn(role="assistant", content="What were you like as a kid?")]
    if user_text is not None:
        turns.append(Turn(role="user", content=user_text))
    return TurnRequest(
        plan=PLAN,
        state=ConversationState(turns=turns, topics=[TopicRecord(topic_id="t", stage="s")],
                                current_topic_id="t", signal=signal),
        options=Options(generate_text=False, **options),
    )


def run(req: TurnRequest):
    return TurnEngine().run(req)


def test_crisis_holds_and_reports_the_full_screen():
    text = "I keep thinking about ending it. Maybe tonight."
    r = run(request(text))
    assert r.decision.action is Action.FOLLOW_UP and r.decision.sub_action is SubAction.HOLD
    assert r.decision.rule_fired == "distress_defer_to_caller"
    safety = r.diagnostics.safety
    assert (safety.level, safety.immediacy) == ("crisis", True)
    assert (safety.screener, safety.patterns_version) == (SCREENER, PATTERNS_VERSION)
    first = safety.findings[0]
    assert first.rule_id == "si_active.ending_it"
    assert text[first.start_offset:first.end_offset] == first.text == "thinking about ending it"


def test_concern_holds_too():
    r = run(request("I'm not going to hurt myself. I just needed to say it."))
    assert r.diagnostics.safety.level == "concern"
    assert r.decision.rule_fired == "distress_defer_to_caller"


@pytest.mark.parametrize("text", [
    "I helped at my parents' dry cleaner.",
    "This commute is killing me.",
    "The first months after she died I was falling apart. I'm not there anymore.",
])
def test_ordinary_grief_and_idioms_do_not_hold(text):
    r = run(request(text))
    assert r.diagnostics.safety.level == "none"
    assert r.decision.rule_fired != "distress_defer_to_caller"


def test_caller_signal_is_kept_but_safety_is_still_reported():
    r = run(request("I want to die.", signal=UserSignal.CLOSING))
    assert r.decision.rule_fired != "distress_defer_to_caller"
    assert r.diagnostics.safety.level == "crisis"


def test_detection_off_still_reports_safety():
    r = run(request("I want to die.", detect_signal=False))
    assert r.decision.rule_fired != "distress_defer_to_caller"
    assert r.diagnostics.safety.level == "crisis"


def test_no_user_turn_has_no_safety():
    assert run(request(None)).diagnostics.safety is None


def test_safety_on_the_wire():
    client = TestClient(build_app(TurnEngine()))
    body = client.post("/v1/turn", json=request("I don't feel safe with myself right now.")
                       .model_dump(mode="json")).json()
    assert body["contract_version"] == "1.3"
    safety = body["diagnostics"]["safety"]
    assert safety["level"] == "crisis"
    assert safety["findings"][0]["category"] == "unsafe_with_self"
    assert set(safety["findings"][0]["modifiers"]) == {
        "negated", "past", "resolved", "hypothetical", "quoted", "idiom"}
