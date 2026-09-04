"""Model-backed sufficiency assessor.

Same port as the deterministic one, so they are interchangeable and directly
comparable on the same labels. That comparison is the point: it tells you what
a model actually buys over regex on this task, rather than assuming it buys
something.

Uses provider-native structured output so the answer is parseable by
construction rather than by prompt-begging.
"""

from __future__ import annotations

import json

from ..domain.enums import Ownership, Specificity
from ..domain.sufficiency import Assessment, SufficiencyComponents
from ..ports.llm import LLMMessage, LLMPort, LLMRequest

SCHEMA = {
    "type": "object",
    "properties": {
        "specificity": {"type": "string", "enum": ["S0", "S1", "S2", "S3"]},
        "ownership": {"type": "string", "enum": ["O0", "O1", "O2"]},
        "scene": {"type": "boolean"},
        "stakes": {"type": "boolean"},
        "action": {"type": "boolean"},
        "outcome": {"type": "boolean"},
        "reflection": {"type": "boolean"},
        "evidence": {
            "type": "string",
            "description": "Short quote from the turn justifying the specificity call.",
        },
    },
    "required": [
        "specificity", "ownership", "scene", "stakes", "action", "outcome",
        "reflection", "evidence",
    ],
    "additionalProperties": False,
}

SYSTEM = """\
You classify a single turn from a reflective interview on two independent axes. \
You are not judging quality, effort, or likeability - only what the turn contains.

SPECIFICITY - how concrete the material is:
  S0  No usable content: a deflection, a one-word answer, a meta-comment, or a
      pure confirmation/closing signal ("yes, that's me", "no, that's enough").
      A confirmation is a SIGNPOST, not material, however long it is.
  S1  A generalization about themselves or the world, with no instance behind it
      ("I'm good at reading people", "I'm a connector").
  S2  A recurring practice, named domain, or habitual action with real detail,
      but no single bounded event ("by seven I was the unofficial translator").
  S3  An EPISODE: one bounded event with all four of scene, stakes, action, and
      outcome. If any of the four is missing, it is S2, not S3.

OWNERSHIP - who did the meaning-making. Judge ONLY this; ignore how vivid or
well-told the turn is.
  O0  Reports events and draws no conclusion ABOUT THEMSELVES. This is the
      default for storytelling, however detailed or moving the story is. A rich
      four-part episode with no interpretive claim is O0, not O2.
  O1  Applies a pre-existing label to themselves, OR accepts/confirms a framing
      the interviewer offered. Confirmations count: "yes, that lands",
      "that's me", "yeah I guess so", "no, that's it" are all O1, because
      accepting a frame is a weak act of meaning-making. A self-label they
      walked in with ("I'm a connector") is O1, never O2.
  O2  States something about their own pattern that they had NOT said before,
      in their own words, derived from their own material - a realization, not
      a description ("I never thought of those as the same thing").

The O2 test: strike out every sentence that describes what happened. If nothing
is left, it is O0 or O1. O2 requires a claim about themselves that survives.

The axes are independent: a confident self-description with no instance is high
ownership and low specificity. Judge them separately.

Be conservative on S3. Over-calling an episode causes an interviewer to move on
too early, which is the specific failure this classification exists to prevent.\
"""


class LLMAssessor:
    name = "llm"

    def __init__(self, llm: LLMPort, effort: str = "low"):
        self.llm = llm
        self.effort = effort

    def assess(self, text: str, prior: SufficiencyComponents) -> Assessment:
        response = self.llm.complete(LLMRequest(
            system=SYSTEM,
            messages=[LLMMessage(role="user", content=f"Turn to classify:\n\n{text}")],
            max_tokens=400,
            effort=self.effort,
            response_schema=SCHEMA,
        ))

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as exc:  # pragma: no cover - structured output
            raise ValueError(
                f"assessor returned unparseable output: {response.text[:200]!r}"
            ) from exc

        turn_components = SufficiencyComponents(
            scene=bool(data["scene"]), stakes=bool(data["stakes"]),
            action=bool(data["action"]), outcome=bool(data["outcome"]),
            reflection=bool(data["reflection"]),
            evidence={"llm": str(data.get("evidence", ""))[:200]},
        )
        merged = prior.merge(turn_components)

        specificity = Specificity(data["specificity"])
        # The model judges this turn; the topic's specificity can only rise as
        # material accumulates, so never let a thin turn erase an earlier episode.
        if merged.narrative_count == 4:
            specificity = max(specificity, Specificity.S3, key=lambda s: s.rank)

        return Assessment(
            specificity=specificity,
            ownership=Ownership(data["ownership"]),
            components=merged,
            confidence=0.8,
            assessor=self.name,
        )
