"""Sufficiency: how much usable material a topic has surfaced.

Two orthogonal axes, because one scale conflates two different things:

  Specificity (S) - how concrete the material is.
  Ownership   (O) - who did the meaning-making.

They are independent in practice. A user can produce a long, confident
self-description with no concrete instance behind it (high O, low S), which is
exactly the case a single scale mis-scores.

Nothing here performs I/O. The deterministic extractor below is a fast path and
a test fixture, NOT a claim of semantic accuracy - its measured agreement with
hand labels is reported by the test suite rather than asserted here. A
model-backed assessor implementing the same interface arrives later.
"""

from __future__ import annotations

import re
from typing import Iterable

from pydantic import BaseModel, Field

from .enums import Ownership, Specificity

# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------


class SufficiencyComponents(BaseModel):
    """The parts of an episode. S3 requires all four narrative components."""

    scene: bool = False
    stakes: bool = False
    action: bool = False
    outcome: bool = False
    reflection: bool = False

    #: component name -> the substring that triggered it (debugging + eval)
    evidence: dict[str, str] = Field(default_factory=dict)

    @property
    def narrative_count(self) -> int:
        return sum([self.scene, self.stakes, self.action, self.outcome])

    def merge(self, other: "SufficiencyComponents") -> "SufficiencyComponents":
        """Accumulate across turns within one topic.

        Sufficiency is a property of the TOPIC, not of a single turn: two
        adjacent turns can each be partial while the pair is nearly an episode.
        Scoring per-turn is what produces the stall failure.
        """
        return SufficiencyComponents(
            scene=self.scene or other.scene,
            stakes=self.stakes or other.stakes,
            action=self.action or other.action,
            outcome=self.outcome or other.outcome,
            reflection=self.reflection or other.reflection,
            evidence={**self.evidence, **other.evidence},
        )


class Assessment(BaseModel):
    """A topic's accumulated sufficiency."""

    specificity: Specificity
    ownership: Ownership
    components: SufficiencyComponents = Field(default_factory=SufficiencyComponents)
    #: 0..1. The deterministic extractor is not confident; a model assessor may be.
    confidence: float = 0.5
    assessor: str = "deterministic"


# --------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------

_SCENE = [
    r"\bI remember\b", r"\bone time\b", r"\bthere was\b", r"\bwhen I was\b",
    r"\bone (?:woman|man|guy|girl|customer|client|patient|kid)\b",
    r"\bmy (?:mom|mother|dad|father|sister|brother|boss|team|manager)\b",
    r"\bthis (?:one|guy|woman|kid|customer)\b", r"\bback (?:then|when)\b",
    r"\bin (?:high school|college|kindergarten)\b",
]
_STAKES = [
    r"\bterrified\b", r"\bafraid\b", r"\bscared\b", r"\bworried\b", r"\banxious\b",
    r"\bfurious\b", r"\bangry\b", r"\bupset\b", r"\bdesperate\b", r"\bhumiliat",
    r"\bat stake\b", r"\bmattered\b", r"\brisk", r"\bon the line\b",
    r"\bgraduation\b", r"\bfuneral\b", r"\bwedding\b", r"\binterview\b",
    r"\blayoff\b", r"\bfired\b", r"\bif (?:we|they|I) (?:didn't|hadn't|couldn't)\b",
]
_ACTION = [
    r"\bI (?:told|said|asked|built|made|got|wrote|set|ran|created|figured|helped)\b",
    r"\bI (?:mapped|flagged|caught|pulled|pushed|started|stopped|changed|fixed)\b",
    r"\bI'd\s+\w+", r"\bI would\s+\w+", r"\bI sat\b", r"\bI put\b", r"\bI took\b",
]
_OUTCOME = [
    r"\bcried\b", r"\bcomped\b", r"\bdissolved\b", r"\bcleared\b", r"\bclicked\b",
    r"\bended up\b", r"\bresulted\b", r"\bso (?:they|she|he|we|it)\b",
    r"\bit worked\b", r"\bnever (?:happened|did)\b", r"\b\d+(?:\.\d+)?\s*%",
    r"\b(?:cut|saved|grew|raised|reduced|increased)\b", r"\bin one (?:session|afternoon|day)\b",
    r"\bbefore (?:they|it|she|he) (?:cut|dropped|left)\b", r"\bcaught\b",
]
_REFLECTION = [
    r"\bI think I(?:'ve)?\b", r"\bI've always\b", r"\bI realize\b", r"\bI guess I(?:'m| am)\b",
    r"\bwhat I care about\b", r"\bthat's me\b", r"\bI never thought of\b",
    r"\bit's how I\b", r"\bthat's the thing I\b", r"\blooking back\b",
]
_CONFIRMATION = [
    r"^\s*(?:yes|yeah|yep|exactly|right)\b", r"\bthat lands\b", r"\bthat's exactly it\b",
    r"\bthat's it\b", r"\byou nailed it\b", r"\bI see it now\b",
]
_SELF_LABEL = [
    r"\bI'm a\b", r"\bI am a\b", r"\bI'm the\b", r"\bmy pattern is\b",
    r"\bI'm good at\b", r"\bI tend to\b", r"\bI'm known for\b",
]
_CLOSING = [
    r"^\s*no[.,!]", r"\bthat covers it\b", r"\bthat's enough\b", r"\bthat's it\b",
    r"\bwe found it\b", r"\bwrite it up\b", r"\bI'm done\b", r"\bthat's all\b",
]
_DEFLECTION = [
    r"\bI don't (?:know|remember)\b", r"\bnot (?:sure|really)\b", r"\bnothing (?:weird|special)\b",
    r"\bnormal I guess\b", r"\bit's fine\b", r"\bno idea\b", r"\bcan't think of\b",
]


def _first_match(text: str, patterns: Iterable[str]) -> str | None:
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            return m.group(0)
    return None


# --------------------------------------------------------------------------
# Extraction + derivation
# --------------------------------------------------------------------------


def extract_components(text: str) -> SufficiencyComponents:
    """Deterministic, explainable feature extraction from one user turn."""
    ev: dict[str, str] = {}
    out = {}
    for name, pats in (
        ("scene", _SCENE), ("stakes", _STAKES), ("action", _ACTION),
        ("outcome", _OUTCOME), ("reflection", _REFLECTION),
    ):
        hit = _first_match(text, pats)
        out[name] = hit is not None
        if hit:
            ev[name] = hit
    return SufficiencyComponents(**out, evidence=ev)


def derive(text: str, components: SufficiencyComponents) -> tuple[Specificity, Ownership]:
    """Map accumulated components + surface cues onto the two axes.

    Deliberately conservative: it will under-call S3 rather than over-call it,
    because a false S3 causes a premature advance, which is the failure mode
    this whole component exists to prevent.
    """
    words = len(text.split())
    deflected = _first_match(text, _DEFLECTION) is not None
    concrete = components.narrative_count

    if concrete == 4:
        spec = Specificity.S3
    elif concrete >= 1:
        spec = Specificity.S2
    elif deflected or words <= 3:
        spec = Specificity.S0
    else:
        spec = Specificity.S1

    # A deflection with no concrete material is S0 regardless of length.
    if deflected and concrete == 0:
        spec = Specificity.S0

    # A confirmation or a closing signal is a SIGNPOST, not material. It can be
    # long and still carry nothing new ("No, that covers it - please write it
    # up."). Scoring these as content is what makes an assessor think a
    # conversation is richer than it is.
    if concrete == 0 and (
        _first_match(text, _CLOSING) or _first_match(text, _CONFIRMATION)
    ):
        spec = Specificity.S0

    if components.reflection:
        own = Ownership.O2
    elif _first_match(text, _CONFIRMATION) or _first_match(text, _SELF_LABEL):
        own = Ownership.O1
    else:
        own = Ownership.O0

    return spec, own


def assess_turn(text: str) -> Assessment:
    """Assess a single user turn in isolation (no topic accumulation)."""
    comps = extract_components(text)
    spec, own = derive(text, comps)
    return Assessment(specificity=spec, ownership=own, components=comps, confidence=0.5)
