"""Tier 3: the turn engine, driven entirely by fakes. No network."""

import pytest

from convint.adapters.llm_fake import FakeLLM
from convint.api.contract import Options, TurnRequest
from convint.app.turn_engine import TurnEngine
from convint.domain import (
    Action, Budget, ConversationState, InterviewPlan, Ownership, Specificity,
    StageSpec, TopicRecord, TopicSpec, Turn, UserSignal,
)
from convint.domain.sufficiency import Assessment, SufficiencyComponents

PLAN = InterviewPlan(
    plan_id="demo",
    stages=[StageSpec(stage_id="early_life", completion_signal="childhood_complete")],
    topics=[TopicSpec(topic_id="childhood", stage="early_life")],
    default_budget=Budget(floor=1, ceiling=3),
)

DRESS = (
    "I remember one woman, furious about a dress. It was her daughter's graduation "
    "and she was terrified. I told my mom that. She comped it and the woman cried."
)


def _state(user_text="I helped at my parents' shop.", used=0, **kw):
    return ConversationState(
        turns=[Turn(role="assistant", content="What were you like as a kid?"),
               Turn(role="user", content=user_text)],
        topics=[TopicRecord(topic_id="childhood", stage="early_life", followups_used=used)],
        current_topic_id="childhood",
        **kw,
    )


def _req(state, generate=False):
    return TurnRequest(plan=PLAN, state=state, options=Options(generate_text=generate))


def test_decision_only_needs_no_llm():
    """The whole gate runs with no adapter configured and no key present."""
    resp = TurnEngine().run(_req(_state()))
    assert resp.decision.action is Action.FOLLOW_UP
    assert resp.message is None


def test_engine_does_not_mutate_caller_state():
    state = _state()
    TurnEngine(llm=FakeLLM(default="q?")).run(_req(state, generate=True))
    assert state.topics[0].followups_used == 0
    assert state.topics[0].specificity is Specificity.S0


def test_followup_advances_the_caller_bookkeeping():
    resp = TurnEngine(llm=FakeLLM(default="Which shop?")).run(_req(_state(), generate=True))
    topic = resp.state_delta.topics[0]
    assert topic.followups_used == 1
    assert topic.asked_questions == ["Which shop?"]


def test_advance_does_not_consume_a_followup():
    """Drive it the way a caller must: one engine call per user turn, carrying
    state_delta forward. Sufficiency accumulates only through that loop."""
    engine = TurnEngine()
    state = _state(user_text=DRESS)

    first = engine.run(_req(state))                      # floor -> follow up, spends 1
    state.topics = first.state_delta.topics
    state.turns.append(Turn(role="user", content="Yes. I think I've always done that."))

    second = engine.run(_req(state))
    assert second.decision.action is Action.ADVANCE
    assert second.state_delta.topics[0].followups_used == 1  # advancing spends nothing


def test_skipping_turns_loses_material():
    """Documents the caller contract: the engine assesses only the LATEST user
    turn and accumulates via state_delta. A caller that batches turns without
    calling per turn silently under-scores the topic."""
    engine = TurnEngine()
    batched = _state(user_text=DRESS, used=1)
    batched.turns.append(Turn(role="user", content="Yes, that's always been true."))

    assert engine.run(_req(batched)).assessment.specificity is not Specificity.S3


def test_synthesize_produces_no_message_even_with_an_llm():
    """Artifact emission is a later milestone; do not fabricate one here."""
    state = _state(signal=UserSignal.CLOSING)
    resp = TurnEngine(llm=FakeLLM(default="should not be used")).run(_req(state, generate=True))
    assert resp.decision.action is Action.SYNTHESIZE
    assert resp.message is None and resp.artifact is None


def test_assessment_is_reported_and_accumulated():
    resp = TurnEngine().run(_req(_state(user_text=DRESS)))
    assert resp.assessment.specificity is Specificity.S3
    assert resp.state_delta.topics[0].specificity is Specificity.S3


def test_custom_assessor_is_used():
    class Always3:
        name = "stub"

        def assess(self, text, prior):
            return Assessment(
                specificity=Specificity.S3, ownership=Ownership.O2,
                components=SufficiencyComponents(), assessor=self.name,
            )

    resp = TurnEngine(assessor=Always3()).run(_req(_state(used=1)))
    assert resp.decision.action is Action.ADVANCE
    assert resp.diagnostics.assessor == "stub"


def test_generated_message_is_grounded_in_the_users_words():
    state = _state(user_text="Made flashcards. Read things out loud until it clicked.")
    resp = TurnEngine(llm=FakeLLM(default="What made you reach for flashcards?")).run(
        _req(state, generate=True)
    )
    assert "flashcards" in resp.message.grounded_on


def test_stacked_questions_are_truncated_to_one():
    """'Stop after a question' enforced mechanically, not by asking nicely."""
    state = _state()
    resp = TurnEngine(llm=FakeLLM(default="Which shop? How old were you? Who else worked there?")).run(
        _req(state, generate=True)
    )
    assert resp.message.text.count("?") == 1


def test_fake_llm_refuses_to_invent_a_response():
    """A test can never silently pass on text nobody wrote."""
    with pytest.raises(KeyError):
        TurnEngine(llm=FakeLLM()).run(_req(_state(), generate=True))


def test_conversation_converges_within_the_ceiling():
    """Feed thin answers forever: the ceiling must break the loop."""
    state = _state()
    engine = TurnEngine()
    seen_rules = []
    for _ in range(10):
        resp = engine.run(_req(state))
        seen_rules.append(resp.decision.rule_fired)
        if resp.decision.action is Action.ADVANCE:
            break
        state.topics = resp.state_delta.topics
        state.turns.append(Turn(role="user", content="I guess. Not really sure."))
    assert seen_rules[-1] == "ceiling_reached"
    assert len(seen_rules) <= 4, seen_rules


def test_rich_material_advances_after_the_floor():
    state = _state(user_text=DRESS, used=0)
    engine = TurnEngine()

    first = engine.run(_req(state))
    assert first.decision.rule_fired == "floor_not_met"

    state.topics = first.state_delta.topics
    state.turns.append(Turn(role="user", content="Yeah, I think I've always seen that."))
    second = engine.run(_req(state))
    assert second.decision.action is Action.ADVANCE
    assert second.decision.completion_signal == "childhood_complete"


def test_generated_question_is_anchored_in_concrete_nouns():
    """The prompt hands the model the user's actual nouns. Measured live, asking
    it to 'use their words' without doing so produced a 0% grounding rate."""
    from convint.app.generator import build_request

    state = _state(user_text="I helped at my parents' dry cleaner in Queens.")
    from convint.domain.gate import decide
    request = build_request(state, decide(state, PLAN), None)
    instruction = request.messages[-1].content
    assert "dry" in instruction and "cleaner" in instruction and "queens" in instruction
