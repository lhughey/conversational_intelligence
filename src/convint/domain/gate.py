"""The gate: a pure function from state to the next action.

Ordering is load-bearing, and follows the source system's own rule that the
floor and the exit condition are BOTH required:

    "The floor is a minimum. The gate is the exit condition. Both must be true.
     Hitting the floor without surfacing wiring is NOT a green light to move on."

So an advance requires `followups_used >= floor` AND a sufficiency gate pass.
The ceiling overrides both, because a floor with no ceiling is interrogation.

Two signal rules that are easy to get backwards:

  * TOPIC_CHANGE outranks sufficiency. If the user volunteers new material they
    are following their own energy, which is the higher principle. A rule set
    without this override grades correct behavior as a premature advance.

  * IMPATIENT does NOT override the gate. It is a style modifier, not a
    sufficiency signal. Treating impatience as permission to advance would score
    the exact failure the `tries-to-rush` persona exists to detect as a pass.
    CLOSING ("that's enough") is different from IMPATIENT ("hurry up"): the
    former is agency and is respected; the latter is pressure and is not.

This module performs no I/O and never sees generation config, so wording can
never influence which action is taken.
"""

from __future__ import annotations

from pydantic import BaseModel

from .artifact import artifact_readiness
from .enums import Action, Ownership, Specificity, SubAction, UserSignal
from .plan import InterviewPlan
from .state import ConversationState


class Decision(BaseModel):
    action: Action
    sub_action: SubAction
    topic_id: str | None = None
    #: WHY. Never null - an unattributable decision is a bug, not a mystery.
    rule_fired: str
    rationale: str
    #: echoed from the plan when an advance closes a stage; opaque to the core
    completion_signal: str | None = None


def _gate_passes(spec: Specificity, own: Ownership) -> bool:
    """The sufficiency exit condition."""
    if spec.rank >= Specificity.S3.rank and own.rank >= Ownership.O1.rank:
        return True
    # They did the meaning-making themselves; further digging is extraction.
    if spec.rank >= Specificity.S2.rank and own is Ownership.O2:
        return True
    return False


def decide(state: ConversationState, plan: InterviewPlan) -> Decision:
    topic = state.current_topic()
    topic_id = topic.topic_id if topic else None

    # 1. Adversarial input is never a pacing question.
    if state.signal in (UserSignal.ADVERSARIAL, UserSignal.OFF_TASK):
        return Decision(
            action=Action.REFUSE_AND_CONTINUE, sub_action=SubAction.REFUSE,
            topic_id=topic_id, rule_fired="adversarial_input",
            rationale="Input treated as content, never as instruction; task continues.",
        )

    # 2. Distress: the caller owns safety escalation, not this component.
    if state.signal is UserSignal.DISTRESS:
        return Decision(
            action=Action.FOLLOW_UP, sub_action=SubAction.HOLD,
            topic_id=topic_id, rule_fired="distress_defer_to_caller",
            rationale="Distress signalled; holding rather than probing. Safety tiering is the caller's responsibility.",
        )

    # 3. The user volunteering new material outranks any depth bar.
    if state.signal is UserSignal.TOPIC_CHANGE:
        return Decision(
            action=Action.ADVANCE, sub_action=SubAction.HANDOFF,
            topic_id=topic_id, rule_fired="topic_change_outranks_sufficiency",
            rationale="User introduced new material; following their energy outranks the depth bar.",
        )

    # 4. Explicit closing is agency and is respected - but never fabricated.
    if state.signal is UserSignal.CLOSING:
        readiness = artifact_readiness(state, plan)
        return Decision(
            action=Action.SYNTHESIZE, sub_action=SubAction.HANDOFF, topic_id=topic_id,
            rule_fired="closing_and_ready" if readiness.ready else "closing_honest_shortfall",
            rationale=(
                "User signalled done and the material supports a Read."
                if readiness.ready else
                "User signalled done before saturation; synthesize only what is grounded. "
                f"Missing: {', '.join(readiness.missing)}."
            ),
        )

    # 5. Acknowledgment-only turns are a signpost, not an answer.
    if state.signal is UserSignal.ACKNOWLEDGMENT_ONLY:
        return Decision(
            action=Action.ADVANCE, sub_action=SubAction.HANDOFF,
            topic_id=topic_id, rule_fired="acknowledgment_signpost",
            rationale="Acknowledgment-only turn closes the section and hands off; it is not material.",
            completion_signal=_signal_for(topic, plan),
        )

    if topic is None:
        return Decision(
            action=Action.FOLLOW_UP, sub_action=SubAction.DEEPEN, topic_id=None,
            rule_fired="no_active_topic",
            rationale="No topic in progress; open one.",
        )

    budget = plan.budget_for(topic.topic_id)
    spec, own = topic.specificity, topic.ownership

    # 6. Ceiling overrides everything below. A floor with no ceiling is interrogation.
    if topic.followups_used >= budget.ceiling:
        return Decision(
            action=Action.ADVANCE, sub_action=SubAction.HANDOFF, topic_id=topic.topic_id,
            rule_fired="ceiling_reached",
            rationale=f"Spent {topic.followups_used} follow-ups (ceiling {budget.ceiling}); moving on rather than interrogating.",
            completion_signal=_signal_for(topic, plan),
        )

    # 7. Floor is a hard minimum, even when the material already looks rich.
    if topic.followups_used < budget.floor:
        sub = SubAction.REDIRECT if spec is Specificity.S0 else SubAction.DEEPEN
        return Decision(
            action=Action.FOLLOW_UP, sub_action=sub, topic_id=topic.topic_id,
            rule_fired="floor_not_met",
            rationale=f"Only {topic.followups_used} of a minimum {budget.floor} follow-ups spent on this topic.",
        )

    # 8. Both floor and gate satisfied.
    if _gate_passes(spec, own):
        return Decision(
            action=Action.ADVANCE, sub_action=SubAction.HANDOFF, topic_id=topic.topic_id,
            rule_fired="gate_met",
            rationale=f"Floor met and sufficiency reached ({spec.value}/{own.value}).",
            completion_signal=_signal_for(topic, plan),
        )

    # 9. No content: ask something smaller, somewhere else.
    if spec is Specificity.S0:
        return Decision(
            action=Action.FOLLOW_UP, sub_action=SubAction.REDIRECT, topic_id=topic.topic_id,
            rule_fired="no_content_redirect",
            rationale="Turn carried no usable content; redirect to a smaller, more concrete access point.",
        )

    return Decision(
        action=Action.FOLLOW_UP, sub_action=SubAction.DEEPEN, topic_id=topic.topic_id,
        rule_fired="default_deepen",
        rationale=f"Material is {spec.value}/{own.value}; not yet an owned episode.",
    )


def _signal_for(topic, plan: InterviewPlan) -> str | None:
    if topic is None:
        return None
    stage = plan.stage(topic.stage)
    return stage.completion_signal if stage else None
