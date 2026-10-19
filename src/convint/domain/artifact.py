"""Artifact readiness: whether the conversation can support a synthesis.

Separate from the gate so that "should we close?" and "can we honestly close?"
stay distinguishable. A user may legitimately end the conversation before the
material supports a full artifact; that produces an honest shortfall, never a
fabricated one.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import Ownership, Specificity
from .plan import InterviewPlan
from .state import ConversationState, TopicRecord

#: A pattern is a disposition only if it shows up in more than one domain.
#: One domain is a job skill.
MIN_DISTINCT_STAGES = 2
MIN_EPISODES = 1


class ArtifactReadiness(BaseModel):
    ready: bool
    missing: list[str] = Field(default_factory=list)
    episodes: int = 0
    distinct_stages: int = 0


def artifact_readiness(state: ConversationState, plan: InterviewPlan) -> ArtifactReadiness:
    missing: list[str] = []

    for stage_id in plan.required_stage_ids():
        if not state.coverage.get(stage_id, False):
            missing.append(f"stage_not_covered:{stage_id}")

    episodes = sum(1 for t in state.topics if t.specificity is Specificity.S3)
    grounded_stages = {
        t.stage for t in state.topics if t.specificity.rank >= Specificity.S2.rank
    }

    if episodes < MIN_EPISODES:
        missing.append("no_episode")
    if len(grounded_stages) < MIN_DISTINCT_STAGES:
        missing.append("single_domain_only")
    if plan.require_pattern_confirmation and not state.pattern_confirmed:
        missing.append("pattern_unconfirmed")

    return ArtifactReadiness(
        ready=not missing,
        missing=missing,
        episodes=episodes,
        distinct_stages=len(grounded_stages),
    )


# --------------------------------------------------------------------------
# Evidence tiering
# --------------------------------------------------------------------------

#: Evidence strength, strongest first. Derived from the specificity ladder
#: rather than invented separately, so tiering falls out of assessment instead
#: of becoming a second judgement that can disagree with the first.
TIER_BY_SPECIFICITY = {
    Specificity.S3: "lived_episode",       # a bounded event they lived
    Specificity.S2: "recurring_practice",  # something they repeatedly do
    Specificity.S1: "self_report",         # a claim about themselves
    Specificity.S0: "unsupported",         # nothing to stand on
}

TIER_RANK = {
    "lived_episode": 3, "recurring_practice": 2, "self_report": 1, "unsupported": 0,
}


class EvidenceItem(BaseModel):
    """One proof point. `where` is the topic it came from; `tier` is how much
    weight it can carry."""

    where: str
    body: str
    tier: str
    specificity: Specificity
    ownership: Ownership


def tier_for(specificity: Specificity) -> str:
    return TIER_BY_SPECIFICITY[specificity]


def collect_evidence(state: ConversationState, min_tier: str = "recurring_practice") -> list[EvidenceItem]:
    """Gather usable evidence, strongest first.

    Anything below `min_tier` is excluded rather than padded - a Read built on
    self-report is the horoscope failure, and the truth floor means emitting
    less is always preferable to emitting more.
    """
    floor = TIER_RANK[min_tier]
    items: list[EvidenceItem] = []
    for topic in state.topics:
        tier = tier_for(topic.specificity)
        if TIER_RANK[tier] < floor:
            continue
        body = _best_quote(state, topic)
        if not body:
            continue
        items.append(EvidenceItem(
            where=topic.topic_id, body=body, tier=tier,
            specificity=topic.specificity, ownership=topic.ownership,
        ))
    return sorted(items, key=lambda e: TIER_RANK[e.tier], reverse=True)


def _best_quote(state: ConversationState, topic: TopicRecord) -> str:
    """The user turn this topic's evidence rests on (`TopicRecord.best_quote`,
    recorded by the engine when that turn raised the topic's specificity).

    Deliberately a verbatim quote: the truth floor requires evidence the user
    actually produced, never a paraphrase that could drift. There is no
    fallback to another turn: borrowing the longest turn in the conversation is
    how a childhood topic ended up quoting a career story. No recorded quote
    returns "", and `collect_evidence` then omits the item rather than emitting
    an empty or borrowed one. Readiness is unaffected - it rests on
    specificity, not on quotes.
    """
    quote = topic.best_quote or ""
    return quote if quote.strip() else ""
