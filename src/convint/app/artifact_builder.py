"""Artifact assembly, with a mechanical truth floor.

Two rules the emitter cannot talk its way out of:

  1. Nothing is emitted unless `artifact_readiness` says the material supports
     it. An honest shortfall beats a fabricated Read.
  2. Every quoted span and every stated number in the output must appear in a
     user turn (`domain/truth_floor.py` says exactly what is and is not
     checked). This is checked in code after generation, not requested in the
     prompt - a model asked nicely not to fabricate will still occasionally
     fabricate. Any violation withholds the Read.
"""

from __future__ import annotations

import json

from ..domain.artifact import artifact_readiness, collect_evidence
from ..domain.plan import InterviewPlan
from ..domain.state import ConversationState
from ..domain.truth_floor import (
    TruthFloorIssue, check_truth_floor, unsupported_numbers, unsupported_quotes,
)
from ..ports.llm import LLMMessage, LLMPort, LLMRequest

DEFAULT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One line naming the through-line."},
        "changes": {"type": "string", "description": "What changes when they are involved."},
        "thrives": {"type": "string", "description": "Conditions where they do their best work."},
        "brings": {"type": "string", "description": "What they bring, in their terms."},
    },
    "required": ["headline", "changes", "thrives", "brings"],
    "additionalProperties": False,
}

SYSTEM = """\
You write a short synthesis from an interview. You may use ONLY what the person \
actually said.

Hard rules:
- Never invent a number, employer, date, job title, or event.
- Any phrase you put in quotation marks must be their exact words.
- Second person ("you"), never third.
- If the material does not support a field, write the least you can honestly say \
rather than padding it.\
"""


class TruthFloorViolation(ValueError):
    """An emitted Read states something the user did not say. `issues` carries
    each unsupported span, its kind and the field it was in."""

    def __init__(self, issues: list[TruthFloorIssue]):
        self.issues = list(issues)
        parts = []
        quotes = [i.span for i in self.issues if i.kind == "quote"]
        numbers = [i.span for i in self.issues if i.kind == "number"]
        if quotes:
            parts.append(f"emitted quotes not found in the user's own words: {quotes}")
        if numbers:
            parts.append(f"emitted numbers not found in the user's own words: {numbers}")
        super().__init__("; ".join(parts) or "truth floor violated")


def _user_text(state: ConversationState) -> str:
    return "\n".join(t.content for t in state.turns if t.role == "user")


def verify_quotes(artifact: dict, state: ConversationState) -> list[str]:
    """Return every quoted span that does not appear verbatim in a user turn."""
    return [i.span for i in unsupported_quotes(artifact, _user_text(state))]


def verify_numbers(artifact: dict, state: ConversationState) -> list[str]:
    """Return every stated number that the user never stated, in any form."""
    return [i.span for i in unsupported_numbers(artifact, _user_text(state))]


def verify_truth_floor(artifact: dict, state: ConversationState) -> list[TruthFloorIssue]:
    """Every mechanically-checkable truth-floor issue, structured."""
    return check_truth_floor(artifact, _user_text(state))


def build_artifact(
    llm: LLMPort, state: ConversationState, plan: InterviewPlan,
    schema: dict | None = None, strict: bool = True,
) -> dict:
    readiness = artifact_readiness(state, plan)
    evidence = collect_evidence(state)

    if not readiness.ready and strict:
        raise ValueError(
            f"artifact not supported by the material; missing: {readiness.missing}"
        )

    schema = schema or DEFAULT_SCHEMA
    transcript = "\n\n".join(
        f"{t.role.upper()}: {t.content}" for t in state.turns
    )
    response = llm.complete(LLMRequest(
        system=SYSTEM,
        messages=[LLMMessage(role="user", content=f"Interview:\n\n{transcript}")],
        max_tokens=900,
        response_schema=schema,
    ))

    artifact = json.loads(response.text)
    issues = verify_truth_floor(artifact, state)
    if issues:
        raise TruthFloorViolation(issues)

    artifact["evidence"] = [e.model_dump(mode="json") for e in evidence]
    artifact["readiness"] = readiness.model_dump(mode="json")
    return artifact
