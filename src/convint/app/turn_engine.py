"""Orchestration: assess -> decide -> generate -> report.

The single entry point every transport wraps. Stateless: the caller's state
object is never mutated; the next state arrives back in `state_delta`.
"""

from __future__ import annotations

from ..adapters.assessor_deterministic import DeterministicAssessor
from ..api.contract import Diagnostics, Message, StateDelta, TurnRequest, TurnResponse
from ..domain.artifact import artifact_readiness
from ..domain.enums import Action, Ownership, Specificity, UserSignal
from ..domain.gate import decide
from ..domain.signals import detect_signal
from ..domain.sufficiency import Assessment
from ..ports.assessor import SufficiencyAssessor
from ..ports.llm import LLMPort
from .moves import select_move


class TurnEngine:
    def __init__(self, assessor: SufficiencyAssessor | None = None, llm: LLMPort | None = None):
        self.assessor = assessor or DeterministicAssessor()
        self.llm = llm

    def run(self, request: TurnRequest) -> TurnResponse:
        # Deep copy: the caller owns its state object and we must not mutate it.
        state = request.state.model_copy(deep=True)
        plan = request.plan

        topic = state.current_topic()
        last_user = state.last_user_turn()

        # Only fills a gap the caller left; never overrides an explicit signal.
        if request.options.detect_signal and state.signal is UserSignal.NONE and last_user:
            state.signal = detect_signal(last_user.content)

        if topic is not None and last_user is not None:
            assessment = self.assessor.assess(last_user.content, topic.components)
            topic.components = assessment.components
            topic.specificity = assessment.specificity
            topic.ownership = assessment.ownership
        elif topic is not None:
            assessment = Assessment(
                specificity=topic.specificity, ownership=topic.ownership,
                components=topic.components, assessor=getattr(self.assessor, "name", "unknown"),
            )
        else:
            assessment = Assessment(
                specificity=Specificity.S0, ownership=Ownership.O0,
                assessor=getattr(self.assessor, "name", "unknown"),
            )

        decision = decide(state, plan)
        readiness = artifact_readiness(state, plan)

        move = None
        message = None
        diagnostics = Diagnostics(assessor=getattr(self.assessor, "name", "unknown"))

        if topic is not None:
            move = select_move(
                decision, topic.components,
                has_earlier_material=len([t for t in state.topics if t.topic_id != topic.topic_id]) > 0,
            )

        # Synthesis: emit only when the material genuinely supports it. An
        # unready close returns readiness.missing instead of a fabricated Read.
        artifact = None
        if decision.action is Action.SYNTHESIZE and self.llm is not None and readiness.ready:
            from .artifact_builder import build_artifact

            artifact = build_artifact(self.llm, state, plan)

        wants_text = request.options.generate_text and decision.action is not Action.SYNTHESIZE
        if wants_text and self.llm is not None:
            from .generator import generate

            text, grounded, diag = generate(self.llm, state, decision, move)
            message = Message(text=text, move_type=move, grounded_on=grounded)
            diagnostics = Diagnostics(
                assessor=diagnostics.assessor, model=diag["model"],
                latency_ms=diag["latency_ms"], usage=diag["usage"],
            )

        # Advance the caller's bookkeeping so a loop converges.
        if topic is not None and decision.action is Action.FOLLOW_UP:
            topic.followups_used += 1
            if message is not None:
                topic.asked_questions.append(message.text)

        return TurnResponse(
            decision=decision,
            assessment=assessment,
            readiness=readiness,
            message=message,
            artifact=artifact,
            state_delta=StateDelta(
                topics=state.topics,
                coverage=state.coverage,
                current_topic_id=state.current_topic_id,
                pattern_confirmed=state.pattern_confirmed,
            ),
            diagnostics=diagnostics,
        )
