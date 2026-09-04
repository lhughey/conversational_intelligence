"""Live smoke tests. Deselected by default; they cost money.

    export ANTHROPIC_API_KEY=...        # or: ant auth login
    make test-live
"""

from __future__ import annotations

import pytest

from convint import config

from convint.adapters.llm_anthropic import AnthropicLLM
from convint.adapters.models import spec
from convint.api.contract import Options, TurnRequest
from convint.app.turn_engine import TurnEngine
from convint.domain import (
    Action, ConversationState, InterviewPlan, StageSpec, TopicRecord, TopicSpec, Turn,
)

pytestmark = pytest.mark.live

config.load()  # this repo's .env only
_HAS_KEY = config.has("ANTHROPIC_API_KEY") or config.has("ANTHROPIC_AUTH_TOKEN")
requires_key = pytest.mark.skipif(not _HAS_KEY, reason="no Anthropic credential in the environment")

PLAN = InterviewPlan(
    plan_id="live",
    stages=[StageSpec(stage_id="early_life", completion_signal="childhood_complete")],
    topics=[TopicSpec(topic_id="childhood", stage="early_life")],
)


@requires_key
def test_adapter_completes_against_the_real_api():
    """Cached, and therefore deterministic after the first run.

    This asserts the single-question rule on ONE sample, which is a smoke test,
    not a measurement: sampling is not tunable on these models, so an uncached
    single draw makes a flaky test out of a real invariant. How OFTEN the rule
    holds is measured over N samples by the testbed instead."""
    from convint.adapters.cache import CachingLLM

    llm = CachingLLM(AnthropicLLM(spec("haiku-4-5")), mode="rw")
    state = ConversationState(
        turns=[Turn(role="assistant", content="What were you like as a kid?"),
               Turn(role="user", content="I helped out at my parents' dry cleaner in Queens.")],
        topics=[TopicRecord(topic_id="childhood", stage="early_life")],
        current_topic_id="childhood",
    )
    resp = TurnEngine(llm=llm).run(
        TurnRequest(plan=PLAN, state=state, options=Options(generate_text=True))
    )

    assert resp.decision.action is Action.FOLLOW_UP
    assert resp.message and resp.message.text.strip()
    assert resp.message.text.count("?") == 1, "single-question rule must hold on real output"
    assert resp.diagnostics.usage.get("output", 0) > 0


@requires_key
def test_sampling_omission_is_what_the_api_actually_wants():
    """Regression guard for the measured 400: a non-default temperature on
    opus/sonnet is rejected, so the adapter must never send one."""
    import anthropic

    client = anthropic.Anthropic()
    with pytest.raises(anthropic.BadRequestError, match="temperature"):
        client.messages.create(
            model="claude-sonnet-5", max_tokens=8,
            extra_body={"temperature": 0.7},  # SDK 1.x dropped the keyword
            messages=[{"role": "user", "content": "hi"}],
        )


@requires_key
def test_haiku_still_accepts_sampling_through_extra_body():
    """The other half of the capability claim: Haiku is the one model where a
    sampling knob still exists."""
    llm = AnthropicLLM(spec("haiku-4-5", temperature=0.4))
    from convint.ports.llm import LLMMessage, LLMRequest

    resp = llm.complete(LLMRequest(
        system="Reply with one word.",
        messages=[LLMMessage(role="user", content="hi")], max_tokens=8,
    ))
    assert resp.text.strip()


# --- assessor + artifact, against real models ------------------------------

@requires_key
def test_llm_assessor_classifies_the_canonical_cases():
    """The three cases that separate the axes. Cached, so re-runs are free."""
    from convint.adapters.assessor_llm import LLMAssessor
    from convint.adapters.cache import CachingLLM
    from convint.adapters.models import build_llm
    from convint.domain import Ownership, Specificity
    from convint.domain.sufficiency import SufficiencyComponents

    a = LLMAssessor(CachingLLM(build_llm("haiku-4-5"), mode="rw"))

    episode = a.assess(
        "I remember one woman, furious about a dress. It was her daughter's graduation "
        "and she was terrified of looking poor. I told my mom that. She comped the "
        "cleaning and the woman cried.", SufficiencyComponents())
    assert episode.specificity is Specificity.S3

    confirmation = a.assess("Yes. That lands. That's me.", SufficiencyComponents())
    assert confirmation.specificity is Specificity.S0, "a confirmation is a signpost, not material"


@requires_key
def test_artifact_emission_respects_the_truth_floor_live():
    """A real model, a real Read, and the quote check run over its actual output."""
    from convint.adapters.cache import CachingLLM
    from convint.adapters.models import build_llm
    from convint.app.artifact_builder import build_artifact, verify_quotes
    from convint.domain import (
        ConversationState, Ownership, Specificity, TopicRecord, Turn,
    )

    plan = InterviewPlan(
        plan_id="live",
        stages=[StageSpec(stage_id="early_life"), StageSpec(stage_id="career")],
        topics=[TopicSpec(topic_id="childhood", stage="early_life"),
                TopicSpec(topic_id="role", stage="career")],
    )
    state = ConversationState(
        turns=[
            Turn(role="user", content=(
                "I remember one woman, furious about a dress. It was her daughter's "
                "graduation and she was terrified of looking poor. I told my mom that. "
                "She comped the cleaning and the woman cried.")),
            Turn(role="user", content=(
                "Billing and clinical blamed each other for months. I saw they were "
                "using the same word to mean different things. I got them in a room "
                "and the standoff dissolved in one session.")),
        ],
        topics=[
            TopicRecord(topic_id="childhood", stage="early_life",
                        specificity=Specificity.S3, ownership=Ownership.O1),
            TopicRecord(topic_id="role", stage="career",
                        specificity=Specificity.S3, ownership=Ownership.O1),
        ],
        coverage={"early_life": True, "career": True},
        pattern_confirmed=True,
    )

    artifact = build_artifact(
        CachingLLM(build_llm("haiku-4-5"), mode="rw"), state, plan
    )
    assert artifact["headline"].strip()
    assert verify_quotes(artifact, state) == []
    assert artifact["evidence"][0]["tier"] == "lived_episode"
