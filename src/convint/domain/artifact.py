"""Artifact readiness: whether the conversation can support a synthesis.

Separate from the gate so that "should we close?" and "can we honestly close?"
stay distinguishable. A user may legitimately end the conversation before the
material supports a full artifact; that produces an honest shortfall, never a
fabricated one.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import Specificity
from .plan import InterviewPlan
from .state import ConversationState

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
