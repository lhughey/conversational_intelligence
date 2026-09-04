"""Closed vocabularies shared by the domain and the wire contract.

Every value here is part of the versioned contract. Adding a member is a minor
contract bump; removing or renaming one is a major bump.
"""

from __future__ import annotations

from enum import Enum


class Action(str, Enum):
    """What the interviewer should do next."""

    FOLLOW_UP = "follow_up"
    ADVANCE = "advance"
    SYNTHESIZE = "synthesize"
    REFUSE_AND_CONTINUE = "refuse_and_continue"


class SubAction(str, Enum):
    """How the action is carried out. Secondary to `Action`."""

    DEEPEN = "deepen"           # more on this topic
    REDIRECT = "redirect"       # smaller question, somewhere else
    REFLECT_PATTERN = "reflect_pattern"
    HANDOFF = "handoff"         # close this stage, open the next
    HOLD = "hold"               # acknowledge without asking
    REFUSE = "refuse"


class Specificity(str, Enum):
    """How concrete the material on a topic is. Ordinal; compare via `rank`."""

    S0 = "S0"  # no content: deflection, meta, one word
    S1 = "S1"  # generalization, no instance
    S2 = "S2"  # recurring practice or named domain, no bounded event
    S3 = "S3"  # episode: scene + stakes + action + outcome

    @property
    def rank(self) -> int:
        return int(self.value[1:])


class Ownership(str, Enum):
    """Who did the meaning-making. Ordinal; compare via `rank`."""

    O0 = "O0"  # reports, draws no conclusion
    O1 = "O1"  # applies a pre-existing label, or confirms the interviewer's framing
    O2 = "O2"  # derives something new, in their own words

    @property
    def rank(self) -> int:
        return int(self.value[1:])


class UserSignal(str, Enum):
    """Intent of the user's latest turn, orthogonal to its content level."""

    NONE = "none"
    CLOSING = "closing"
    IMPATIENT = "impatient"
    ACKNOWLEDGMENT_ONLY = "acknowledgment_only"
    TOPIC_CHANGE = "topic_change"
    DEFLECTION = "deflection"
    ADVERSARIAL = "adversarial"
    OFF_TASK = "off_task"
    DISTRESS = "distress"


class MoveType(str, Enum):
    """The kind of follow-up. Selecting from a taxonomy produces variety
    structurally, rather than relying on sampling randomness."""

    ASK_FOR_SCENE = "ask_for_scene"
    ASK_WHAT_WAS_AT_STAKE = "ask_what_was_at_stake"
    ASK_WHAT_THEY_DID = "ask_what_they_did"
    ASK_WHAT_SURPRISED = "ask_what_surprised"
    REFLECT_AND_CHECK = "reflect_and_check"
    CONTRAST_WITH_EARLIER = "contrast_with_earlier"


def at_least(value: Specificity | Ownership, floor: Specificity | Ownership) -> bool:
    """Ordinal comparison that does not rely on string ordering."""
    return value.rank >= floor.rank
