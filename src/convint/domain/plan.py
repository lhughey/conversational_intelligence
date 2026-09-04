"""The InterviewPlan: caller-supplied configuration.

The core knows nothing about any particular product. Stages, topics, budgets,
and completion-signal names all arrive from the caller, which is how a consumer
routes its own tool names (e.g. `childhood_complete`) through the component
without the component ever knowing they exist.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class Budget(BaseModel):
    """Two-sided, deliberately.

    A ceiling alone rewards under-asking, which is the failure this component
    exists to prevent; a floor alone permits interrogation. Both are required.
    """

    floor: int = Field(default=1, ge=0)
    ceiling: int = Field(default=3, ge=1)

    @model_validator(mode="after")
    def _check(self) -> "Budget":
        if self.ceiling < self.floor:
            raise ValueError(f"ceiling ({self.ceiling}) must be >= floor ({self.floor})")
        return self


class TopicSpec(BaseModel):
    topic_id: str
    stage: str
    budget: Budget | None = None  # falls back to the plan default


class StageSpec(BaseModel):
    stage_id: str
    required: bool = True
    #: opaque to the core; echoed back to the caller when the stage closes
    completion_signal: str | None = None


class InterviewPlan(BaseModel):
    plan_id: str
    version: str = "1.0"
    stages: list[StageSpec] = Field(default_factory=list)
    topics: list[TopicSpec] = Field(default_factory=list)
    default_budget: Budget = Field(default_factory=Budget)

    #: require the user to confirm the named pattern before an artifact may emit
    require_pattern_confirmation: bool = True

    @model_validator(mode="after")
    def _topics_reference_known_stages(self) -> "InterviewPlan":
        known = {s.stage_id for s in self.stages}
        unknown = {t.stage for t in self.topics} - known
        if unknown:
            raise ValueError(f"topics reference undeclared stages: {sorted(unknown)}")
        return self

    def budget_for(self, topic_id: str) -> Budget:
        spec = next((t for t in self.topics if t.topic_id == topic_id), None)
        if spec is not None and spec.budget is not None:
            return spec.budget
        return self.default_budget

    def stage_for(self, topic_id: str) -> str | None:
        spec = next((t for t in self.topics if t.topic_id == topic_id), None)
        return spec.stage if spec else None

    def stage(self, stage_id: str) -> StageSpec | None:
        return next((s for s in self.stages if s.stage_id == stage_id), None)

    def required_stage_ids(self) -> list[str]:
        return [s.stage_id for s in self.stages if s.required]
