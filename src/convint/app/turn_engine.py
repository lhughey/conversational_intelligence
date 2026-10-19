"""Orchestration: assess -> decide -> generate -> report.

The single entry point every transport wraps. Stateless: the caller's state
object is never mutated; the next state arrives back in `state_delta`.

A model failure never fails a turn. The decision is deterministic given an
assessment, so: a failing model-backed assessor is re-run with the
deterministic one, a failing generator returns `message: null`, and a failing
or truth-floor-violating Read returns `artifact: null`. Each is named in
`diagnostics.warnings` and sets `diagnostics.degraded`. The catches wrap only
the model calls; errors in the deterministic path propagate.
"""

from __future__ import annotations

import time

from ..adapters.assessor_deterministic import DeterministicAssessor
from ..api.contract import Diagnostics, Message, StateDelta, TurnRequest, TurnResponse
from ..domain.artifact import artifact_readiness
from ..domain.enums import Action, Ownership, Specificity, UserSignal
from ..domain.gate import decide
from ..domain.crisis import screen_text
from ..domain.signals import detect_signal
from ..domain.state import TopicRecord
from ..domain.sufficiency import Assessment, SufficiencyComponents
from ..ports.assessor import SufficiencyAssessor
from ..ports.llm import LLMPort
from .metering import MeteredLLM, metering
from .moves import select_move


def _describe(exc: Exception, limit: int = 200) -> str:
    text = (str(exc).strip().splitlines() or [""])[0]
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _name(assessor: SufficiencyAssessor) -> str:
    return getattr(assessor, "name", "unknown")


_COMPONENT_FLAGS = ("scene", "stakes", "action", "outcome", "reflection")


def _record_best_quote(
    topic: TopicRecord, user_text: str, assessment: Assessment,
    prior_specificity: Specificity, prior_components: SufficiencyComponents,
) -> None:
    """Keep the user turn this topic's evidence rests on.

    `user_text` is always the last USER turn, never assistant text. The quote
    moves only when this turn strictly raised the topic's specificity; a tie
    keeps the earlier quote. A topic with no quote yet (one the caller built,
    or state from before 1.2) takes this turn only if the turn itself added
    material - specificity is cumulative, so a bare "Yes." on an S2 topic still
    assesses S2 and must not become the quote.
    """
    spec = assessment.specificity
    if spec.rank <= Specificity.S0.rank:
        return
    raised = spec.rank > prior_specificity.rank
    added = any(
        getattr(assessment.components, f) and not getattr(prior_components, f)
        for f in _COMPONENT_FLAGS
    )
    if raised or (topic.best_quote is None and added):
        topic.best_quote = user_text


class TurnEngine:
    def __init__(
        self,
        assessor: SufficiencyAssessor | None = None,
        llm: LLMPort | None = None,
        *,
        assessor_model: str | None = None,
        startup_warnings: list[str] | None = None,
    ):
        #: always available: `assess="deterministic"` and every fallback use it
        self.fallback_assessor = DeterministicAssessor()
        self.assessor = assessor or self.fallback_assessor
        # Metered so diagnostics carry usage/cost. Assessor usage is counted
        # only when the assessor's own adapter is metered (build_engine does
        # that); an assessor injected directly here is not counted.
        self.llm = llm if llm is None or isinstance(llm, MeteredLLM) else MeteredLLM(llm)
        self.assessor_model = assessor_model
        #: degradations decided at construction (e.g. a missing credential)
        self.startup_warnings = list(startup_warnings or [])

    @property
    def model_backed_assessor(self) -> bool:
        return not isinstance(self.assessor, DeterministicAssessor)

    def _choose_assessor(self, mode: str, warnings: list[str]) -> SufficiencyAssessor:
        if mode == "deterministic":
            return self.fallback_assessor
        if mode == "llm" and not self.model_backed_assessor:
            warnings.append(
                "assess_llm_unavailable: the server has no model-backed assessor "
                "configured; used deterministic"
            )
            return self.fallback_assessor
        return self.assessor

    def _assess(
        self, assessor: SufficiencyAssessor, text: str, prior: SufficiencyComponents,
        warnings: list[str],
    ) -> tuple[Assessment, SufficiencyAssessor]:
        if assessor is self.fallback_assessor:
            return assessor.assess(text, prior), assessor
        try:
            return assessor.assess(text, prior), assessor
        except Exception as exc:  # model path: API, truncation, refusal, bad JSON
            warnings.append(f"assessor_fallback: {_describe(exc)}")
            return self.fallback_assessor.assess(text, prior), self.fallback_assessor

    def run(self, request: TurnRequest) -> TurnResponse:
        started = time.monotonic()
        with metering() as meter:
            return self._run(request, meter, started)

    def _run(self, request: TurnRequest, meter, started: float) -> TurnResponse:
        # Deep copy: the caller owns its state object and we must not mutate it.
        state = request.state.model_copy(deep=True)
        plan = request.plan
        warnings: list[str] = list(self.startup_warnings)

        topic = state.current_topic()
        last_user = state.last_user_turn()

        # Screened on every turn and always reported, so the caller sees it
        # even when it sent its own signal.
        safety = screen_text(last_user.content) if last_user else None

        # Only fills a gap the caller left; never overrides an explicit signal.
        if request.options.detect_signal and state.signal is UserSignal.NONE and last_user:
            state.signal = detect_signal(last_user.content, safety)

        used = self._choose_assessor(request.options.assess, warnings)
        if topic is not None and last_user is not None:
            prior_specificity, prior_components = topic.specificity, topic.components
            assessment, used = self._assess(used, last_user.content, topic.components, warnings)
            topic.components = assessment.components
            topic.specificity = assessment.specificity
            topic.ownership = assessment.ownership
            _record_best_quote(topic, last_user.content, assessment,
                               prior_specificity, prior_components)
        elif topic is not None:
            assessment = Assessment(
                specificity=topic.specificity, ownership=topic.ownership,
                components=topic.components, assessor=_name(used),
            )
        else:
            assessment = Assessment(
                specificity=Specificity.S0, ownership=Ownership.O0, assessor=_name(used),
            )

        decision = decide(state, plan)
        readiness = artifact_readiness(state, plan)

        move = None
        message = None
        model_called = False
        generated_model = None

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

            model_called = True
            try:
                artifact = build_artifact(self.llm, state, plan)
            except Exception as exc:  # incl. TruthFloorViolation: withhold, never fabricate
                warnings.append(f"artifact_withheld: {_describe(exc)}")

        wants_text = request.options.generate_text and decision.action is not Action.SYNTHESIZE
        if wants_text and self.llm is not None:
            from .generator import generate

            model_called = True
            try:
                text, grounded, diag = generate(self.llm, state, decision, move)
            except Exception as exc:
                warnings.append(f"generation_failed: {_describe(exc)}")
            else:
                message = Message(text=text, move_type=move, grounded_on=grounded)
                generated_model = diag["model"] or None

        # Advance the caller's bookkeeping so a loop converges.
        if topic is not None and decision.action is Action.FOLLOW_UP:
            topic.followups_used += 1
            if message is not None:
                topic.asked_questions.append(message.text)

        diagnostics = Diagnostics(
            assessor=_name(used),
            model=generated_model or (self.llm.model_id if model_called else None),
            assessor_model=self.assessor_model if used is self.assessor
            and self.model_backed_assessor else None,
            latency_ms=int((time.monotonic() - started) * 1000),
            usage=dict(meter.usage),
            cost_usd=meter.cost_usd,
            warnings=warnings,
            degraded=bool(warnings),
            safety=safety,
        )

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
