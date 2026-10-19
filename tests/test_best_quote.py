"""Evidence quotes come from the topic they support (`TopicRecord.best_quote`).

The bug this replaces: `_best_quote` returned the longest user turn in the
whole conversation, so a childhood topic's evidence quoted a career story.
"""

import json

from convint.adapters.llm_fake import FakeLLM
from convint.api.contract import Options, TurnRequest, TurnResponse
from convint.app.artifact_builder import build_artifact
from convint.app.turn_engine import TurnEngine
from convint.domain import (
    Budget, ConversationState, InterviewPlan, Ownership, Specificity, StageSpec,
    TopicRecord, TopicSpec, Turn,
)
from convint.domain.artifact import collect_evidence

PLAN = InterviewPlan(
    plan_id="bq",
    stages=[StageSpec(stage_id="early_life"), StageSpec(stage_id="career")],
    topics=[TopicSpec(topic_id="childhood", stage="early_life"),
            TopicSpec(topic_id="role", stage="career")],
    default_budget=Budget(floor=1, ceiling=6),
)

# deterministic specificity of each turn on its own, checked in the tests below
S1_SATURDAY = "Every Saturday I worked the counter at my parents' shop."
S1_SUNDAY = "Every Sunday I folded shirts in the back room."
S2_HELPED = "I helped at my parents' shop."
S3_DRESS = (
    "I remember one woman, furious about a dress. It was her daughter's graduation "
    "and she was terrified. I told my mom that. She comped it and the woman cried."
)
CAREER_LONG = (
    "At work I run the weekly planning meeting for three teams and I rewrite the "
    "roadmap every quarter so engineering and sales agree on what done means, and "
    "I keep a running document of every decision so nobody relitigates it later."
)
CONFIRM = "Yes. That lands."
STAGE = {"childhood": "early_life", "role": "career"}


def _run(state: ConversationState, engine: TurnEngine | None = None) -> TurnResponse:
    """One call, round-tripped through JSON as a real transport would."""
    resp = (engine or TurnEngine()).run(
        TurnRequest(plan=PLAN, state=state, options=Options(generate_text=False))
    )
    return TurnResponse.model_validate_json(resp.model_dump_json())


def _say(state: ConversationState, text: str, topic_id: str,
         engine: TurnEngine | None = None) -> ConversationState:
    """The caller's loop: append the user turn, call, persist `state_delta`."""
    if state.topic(topic_id) is None:
        state.topics.append(TopicRecord(topic_id=topic_id, stage=STAGE[topic_id]))
    state.current_topic_id = topic_id
    state.turns.append(Turn(role="user", content=text))
    delta = _run(state, engine).state_delta
    state = state.model_copy(update={
        "topics": delta.topics, "coverage": delta.coverage,
        "current_topic_id": delta.current_topic_id,
    })
    state.turns.append(Turn(role="assistant", content=f"(interviewer reply to: {text[:20]})"))
    return state


def _quote(state: ConversationState, topic_id: str) -> str | None:
    return state.topic(topic_id).best_quote


def test_childhood_evidence_quotes_a_childhood_turn_not_the_longest_turn():
    """The original bug: a longer career turn must not become childhood's quote."""
    assert len(CAREER_LONG) > len(S3_DRESS)
    state = ConversationState()
    state = _say(state, S3_DRESS, "childhood")
    state = _say(state, CAREER_LONG, "role")

    bodies = {e.where: e.body for e in collect_evidence(state, min_tier="self_report")}
    assert bodies == {"childhood": S3_DRESS, "role": CAREER_LONG}


def test_best_quote_advances_only_on_strictly_higher_specificity():
    state = ConversationState()

    state = _say(state, S1_SATURDAY, "childhood")
    assert state.topic("childhood").specificity is Specificity.S1
    assert _quote(state, "childhood") == S1_SATURDAY

    state = _say(state, S1_SUNDAY, "childhood")          # tie: keep the earlier quote
    assert state.topic("childhood").specificity is Specificity.S1
    assert _quote(state, "childhood") == S1_SATURDAY

    state = _say(state, S2_HELPED, "childhood")          # S1 -> S2: move
    assert state.topic("childhood").specificity is Specificity.S2
    assert _quote(state, "childhood") == S2_HELPED

    state = _say(state, S3_DRESS, "childhood")           # S2 -> S3: move
    assert state.topic("childhood").specificity is Specificity.S3
    assert _quote(state, "childhood") == S3_DRESS

    state = _say(state, S2_HELPED + " Every day.", "childhood")  # no rise: keep
    assert _quote(state, "childhood") == S3_DRESS


def test_an_s0_turn_never_becomes_the_quote():
    state = _say(ConversationState(), CONFIRM, "childhood")
    assert state.topic("childhood").specificity is Specificity.S0
    assert _quote(state, "childhood") is None
    assert collect_evidence(state, min_tier="unsupported") == []


def test_a_bare_confirmation_does_not_fill_a_caller_built_topic():
    """Specificity is cumulative: a "Yes." on an S2 topic still assesses S2. A
    topic with no quote (caller-built, or pre-1.2 state) takes a turn only if
    the turn itself added material."""
    from convint.domain.sufficiency import SufficiencyComponents

    state = ConversationState(topics=[TopicRecord(
        topic_id="childhood", stage="early_life", specificity=Specificity.S2,
        components=SufficiencyComponents(action=True),
    )])
    state = _say(state, CONFIRM, "childhood")
    assert _quote(state, "childhood") is None

    state = _say(state, S3_DRESS, "childhood")
    assert _quote(state, "childhood") == S3_DRESS


def test_best_quote_is_only_ever_the_users_words():
    state = ConversationState(
        turns=[Turn(role="user", content=S3_DRESS),
               Turn(role="assistant", content="That woman was terrified - and you saw it?")],
        topics=[TopicRecord(topic_id="childhood", stage="early_life")],
        current_topic_id="childhood",
    )
    topic = _run(state).state_delta.topics[0]
    assert topic.best_quote == S3_DRESS

    only_assistant = ConversationState(
        turns=[Turn(role="assistant", content=S3_DRESS)],
        topics=[TopicRecord(topic_id="childhood", stage="early_life")],
        current_topic_id="childhood",
    )
    assert _run(only_assistant).state_delta.topics[0].best_quote is None


def test_best_quote_is_recorded_when_the_assessor_falls_back():
    class Broken:
        name = "broken"

        def assess(self, text, prior):
            raise RuntimeError("model down")

    engine = TurnEngine(assessor=Broken())
    state = ConversationState(
        turns=[Turn(role="user", content=S3_DRESS)],
        topics=[TopicRecord(topic_id="childhood", stage="early_life")],
        current_topic_id="childhood",
    )
    resp = _run(state, engine)
    assert resp.diagnostics.warnings[0].startswith("assessor_fallback")
    assert resp.state_delta.topics[0].best_quote == S3_DRESS


def test_best_quote_survives_the_wire():
    state = _say(ConversationState(), S3_DRESS, "childhood")
    wire = json.loads(TurnRequest(plan=PLAN, state=state).model_dump_json())
    assert wire["state"]["topics"][0]["best_quote"] == S3_DRESS
    assert TurnRequest.model_validate(wire).state.topics[0].best_quote == S3_DRESS


def test_caller_built_topic_without_a_quote_gets_no_fabricated_evidence():
    """No recorded quote -> no evidence item. Never a borrowed turn, never an
    empty body. Readiness still rests on specificity, so the Read can emit."""
    state = ConversationState(
        turns=[Turn(role="user", content=CAREER_LONG)],
        topics=[
            TopicRecord(topic_id="childhood", stage="early_life",
                        specificity=Specificity.S3, ownership=Ownership.O1),
            TopicRecord(topic_id="role", stage="career",
                        specificity=Specificity.S2, ownership=Ownership.O1,
                        best_quote=CAREER_LONG),
        ],
        coverage={"early_life": True, "career": True},
        pattern_confirmed=True,
    )
    ev = collect_evidence(state)
    assert [(e.where, e.body) for e in ev] == [("role", CAREER_LONG)]

    art = build_artifact(FakeLLM(default=json.dumps(
        {"headline": "h", "changes": "c", "thrives": "t", "brings": "b"})), state, PLAN)
    assert art["readiness"]["ready"] is True
    assert [e["where"] for e in art["evidence"]] == ["role"]
    assert all(e["body"] for e in art["evidence"])


def test_whitespace_quote_is_treated_as_no_quote():
    state = ConversationState(topics=[TopicRecord(
        topic_id="childhood", stage="early_life", specificity=Specificity.S3,
        best_quote="   ",
    )])
    assert collect_evidence(state) == []
