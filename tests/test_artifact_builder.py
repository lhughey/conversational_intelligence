"""Artifact emission and its truth floor."""

import json

import pytest

from convint.app.artifact_builder import (
    DEFAULT_SCHEMA, TruthFloorViolation, build_artifact, verify_numbers, verify_quotes,
)
from convint.adapters.llm_fake import FakeLLM
from convint.domain import (
    ConversationState, InterviewPlan, Ownership, Specificity, StageSpec,
    TopicRecord, TopicSpec, Turn,
)
from convint.domain.artifact import TIER_RANK, collect_evidence, tier_for

PLAN = InterviewPlan(
    plan_id="t",
    stages=[StageSpec(stage_id="early_life"), StageSpec(stage_id="career")],
    topics=[TopicSpec(topic_id="childhood", stage="early_life"),
            TopicSpec(topic_id="role", stage="career")],
)

USER_TEXT = "I told my mom that. She comped the cleaning and the woman cried."
CAREER_TEXT = "Every week I sit billing and clinical down and find the word they disagree on."


def _state(**kw):
    base = dict(
        turns=[Turn(role="user", content=USER_TEXT), Turn(role="user", content=CAREER_TEXT)],
        topics=[
            TopicRecord(topic_id="childhood", stage="early_life",
                        specificity=Specificity.S3, ownership=Ownership.O1,
                        best_quote=USER_TEXT),
            TopicRecord(topic_id="role", stage="career",
                        specificity=Specificity.S2, ownership=Ownership.O1,
                        best_quote=CAREER_TEXT),
        ],
        coverage={"early_life": True, "career": True},
        pattern_confirmed=True,
    )
    base.update(kw)
    return ConversationState(**base)


def _artifact_json(**over):
    base = {"headline": "You find the real need", "changes": "Things clear up",
            "thrives": "Where terms are contested", "brings": "Translation"}
    base.update(over)
    return json.dumps(base)


# --- tiering ---------------------------------------------------------------

def test_tiers_derive_from_the_specificity_ladder():
    """Tiering falls out of assessment rather than being a second judgement
    that could disagree with the first."""
    assert tier_for(Specificity.S3) == "lived_episode"
    assert tier_for(Specificity.S2) == "recurring_practice"
    assert tier_for(Specificity.S1) == "self_report"
    assert TIER_RANK["lived_episode"] > TIER_RANK["self_report"]


def test_evidence_is_ordered_strongest_first():
    ev = collect_evidence(_state())
    assert [e.tier for e in ev] == ["lived_episode", "recurring_practice"]


def test_weak_evidence_is_excluded_not_padded():
    """A Read built on self-report is the horoscope failure."""
    state = _state(topics=[TopicRecord(topic_id="x", stage="early_life",
                                       specificity=Specificity.S1)])
    assert collect_evidence(state) == []


# --- truth floor -----------------------------------------------------------

def test_verify_quotes_accepts_the_users_own_words():
    assert verify_quotes({"a": 'You said "I told my mom that".'}, _state()) == []


def test_verify_quotes_catches_a_fabricated_quote():
    bad = verify_quotes({"a": 'You said "I ran the entire division".'}, _state())
    assert bad == ["I ran the entire division"]


def test_build_artifact_rejects_fabrication_mechanically():
    """Checked in code after generation, because a model asked nicely not to
    fabricate will still occasionally fabricate."""
    llm = FakeLLM(default=_artifact_json(headline='You "scaled a 400-person org"'))
    with pytest.raises(TruthFloorViolation, match="not found in the user"):
        build_artifact(llm, _state(), PLAN)


# --- readiness gating ------------------------------------------------------

def test_artifact_refuses_to_emit_when_unsupported():
    state = _state(pattern_confirmed=False)
    with pytest.raises(ValueError, match="not supported"):
        build_artifact(FakeLLM(default=_artifact_json()), state, PLAN)


def test_successful_emission_carries_evidence_and_readiness():
    art = build_artifact(FakeLLM(default=_artifact_json()), _state(), PLAN)
    assert art["headline"]
    assert art["readiness"]["ready"] is True
    assert art["evidence"][0]["tier"] == "lived_episode"


def test_emission_requests_a_structured_schema():
    llm = FakeLLM(default=_artifact_json())
    build_artifact(llm, _state(), PLAN)
    assert llm.calls[0].response_schema == DEFAULT_SCHEMA


def test_caller_can_supply_its_own_artifact_schema():
    """Generic core: the consumer decides the Read's shape."""
    schema = {"type": "object", "properties": {"summary": {"type": "string"}},
              "required": ["summary"], "additionalProperties": False}
    llm = FakeLLM(default=json.dumps({"summary": "ok"}))
    art = build_artifact(llm, _state(), PLAN, schema=schema)
    assert art["summary"] == "ok"
    assert llm.calls[0].response_schema == schema


def test_verify_quotes_catches_curly_and_single_quoted_fabrication():
    art = {"a": "You said “I ran the entire division”.",
           "b": "and ‘I hired the whole team’."}
    assert verify_quotes(art, _state()) == ["I ran the entire division", "I hired the whole team"]


def test_verify_quotes_accepts_curly_quoted_own_words():
    assert verify_quotes({"a": "You said “I told my mom that”."}, _state()) == []


def test_build_artifact_withholds_an_invented_number():
    """The truth floor is hard: a number the user never said withholds the Read."""
    llm = FakeLLM(default=_artifact_json(brings="You increased revenue by 300%"))
    with pytest.raises(TruthFloorViolation, match="numbers not found in the user") as err:
        build_artifact(llm, _state(), PLAN)
    assert [(i.kind, i.field, i.span) for i in err.value.issues] == [
        ("number", "brings", "300%"),
    ]


def test_build_artifact_keeps_a_number_the_user_said():
    state = _state(turns=[Turn(role="user", content=USER_TEXT + " That was 300 percent busier.")])
    art = build_artifact(
        FakeLLM(default=_artifact_json(brings="A 300% busier front desk")), state, PLAN,
    )
    assert art["brings"] == "A 300% busier front desk"


def test_verify_numbers_reports_spans():
    assert verify_numbers({"a": "You led 40 people for six years"}, _state()) == ["40", "six"]
