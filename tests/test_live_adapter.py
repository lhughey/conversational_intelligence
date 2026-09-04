"""Live smoke tests. Deselected by default; they cost money.

    export ANTHROPIC_API_KEY=...        # or: ant auth login
    make test-live
"""

from __future__ import annotations

import os

import pytest

from convint.adapters.llm_anthropic import AnthropicLLM
from convint.adapters.models import spec
from convint.api.contract import Options, TurnRequest
from convint.app.turn_engine import TurnEngine
from convint.domain import (
    Action, ConversationState, InterviewPlan, StageSpec, TopicRecord, TopicSpec, Turn,
)

pytestmark = pytest.mark.live

_HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
requires_key = pytest.mark.skipif(not _HAS_KEY, reason="no Anthropic credential in the environment")

PLAN = InterviewPlan(
    plan_id="live",
    stages=[StageSpec(stage_id="early_life", completion_signal="childhood_complete")],
    topics=[TopicSpec(topic_id="childhood", stage="early_life")],
)


@requires_key
def test_adapter_completes_against_the_real_api():
    llm = AnthropicLLM(spec("haiku-4-5"))
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
