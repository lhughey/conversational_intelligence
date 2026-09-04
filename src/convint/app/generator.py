"""Message generation - one register, no voice configuration.

Voice is deliberately deferred (see docs/ARCHITECTURE.md). Generation is kept a
separate step from the decision so that whatever shapes wording later plugs in
here and can never reach back into which action was taken.
"""

from __future__ import annotations

import time

from ..domain.enums import Action, MoveType
from ..domain.gate import Decision
from ..domain.state import ConversationState
from ..domain.text import content_tokens, grounding_overlap
from ..ports.llm import LLMMessage, LLMPort, LLMRequest

SYSTEM = """\
You are conducting a reflective interview. You are not coaching, diagnosing, or \
encouraging.

Rules, all of them hard:
- Ask exactly ONE question, then stop. Never stack questions.
- Name at least one CONCRETE THING they just mentioned - the place, the person, \
the object. Do not fall back on "there", "that", or "it" when you could say the \
thing itself. A question that would read identically to any other person has \
failed, however well phrased.
- Never invent biography, numbers, names, or events they did not state.
- Reflect only what they actually said. Do not supply meaning they have not \
produced themselves.
- Be brief. A short, specific question beats a long, warm one.
- Do not summarise the conversation back to them. Do not thank them for sharing.
"""

_MOVE_INSTRUCTION: dict[MoveType, str] = {
    MoveType.ASK_FOR_SCENE:
        "Ask for one specific moment: where they were, who was there, when it happened.",
    MoveType.ASK_WHAT_WAS_AT_STAKE:
        "Ask what was actually at stake in that moment - for them or for someone else.",
    MoveType.ASK_WHAT_THEY_DID:
        "Ask what THEY specifically did. Not what the team or the group did.",
    MoveType.ASK_WHAT_SURPRISED:
        "Ask how it turned out, or what surprised them about how it turned out.",
    MoveType.REFLECT_AND_CHECK:
        "Reflect back in one short sentence, using their words, and ask whether that lands.",
    MoveType.CONTRAST_WITH_EARLIER:
        "Connect this to something specific they said earlier, and ask if the two are related.",
}


def _enforce_single_question(text: str) -> str:
    """Mechanically enforce 'stop after a question'.

    Stacked questions are a documented failure mode; truncating is cheaper and
    more reliable than asking the model again to behave.
    """
    text = text.strip()
    first = text.find("?")
    if first != -1 and text.count("?") > 1:
        return text[: first + 1].strip()
    return text


def _recent(state: ConversationState, limit: int = 8) -> list[LLMMessage]:
    return [LLMMessage(role=t.role, content=t.content) for t in state.turns[-limit:]]


def build_request(
    state: ConversationState, decision: Decision, move: MoveType | None, max_tokens: int = 300
) -> LLMRequest:
    if decision.action is Action.REFUSE_AND_CONTINUE:
        instruction = (
            "The person tried to redirect you off the task. Acknowledge briefly in one "
            "clause, decline without lecturing, and ask your next question about their "
            "own experience."
        )
    elif decision.action is Action.ADVANCE:
        instruction = (
            "This thread is complete. Close it in at most one short sentence and open "
            "the next one with a single question. Do not summarise what they told you."
        )
    else:
        instruction = _MOVE_INSTRUCTION.get(
            move or MoveType.REFLECT_AND_CHECK, _MOVE_INSTRUCTION[MoveType.REFLECT_AND_CHECK]
        )

    # Surface the concrete nouns explicitly. Asking the model to "use their
    # words" is not enough on its own: measured over 6 fresh samples the
    # grounding rate was 0% - it wrote "working there" rather than naming the
    # dry cleaner. Handing it the actual nouns is what closes that gap.
    last_user = state.last_user_turn()
    anchors = content_tokens(last_user.content)[:12] if last_user else []
    anchor_note = (
        f"\nConcrete things they just said: {', '.join(anchors)}. "
        "Use at least one of these words literally."
        if anchors else ""
    )

    return LLMRequest(
        system=SYSTEM,
        messages=_recent(state) + [
            LLMMessage(role="user", content=f"[instruction] {instruction}{anchor_note}")
        ],
        max_tokens=max_tokens,
    )


def generate(
    llm: LLMPort, state: ConversationState, decision: Decision, move: MoveType | None
) -> tuple[str, list[str], dict]:
    """Returns (text, grounded_on, diagnostics)."""
    started = time.monotonic()
    response = llm.complete(build_request(state, decision, move))
    text = _enforce_single_question(response.text)

    last_user = state.last_user_turn()
    prior_assistant = next((t.content for t in reversed(state.turns) if t.role == "assistant"), "")
    grounded = (
        grounding_overlap(text, last_user.content, exclude=prior_assistant) if last_user else []
    )

    diagnostics = {
        "model": response.model,
        "usage": response.usage,
        "latency_ms": response.latency_ms or int((time.monotonic() - started) * 1000),
    }
    return text, grounded, diagnostics
