"""The versioned wire contract - the only thing this component and its consumer
share. Neither repo imports the other's types.

MCP, HTTP, subprocess, and in-process callers all speak exactly these models.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain.artifact import ArtifactReadiness
from ..domain.enums import MoveType
from ..domain.gate import Decision
from ..domain.plan import InterviewPlan
from ..domain.state import ConversationState, TopicRecord
from ..domain.sufficiency import Assessment

#: Bump the minor for additive changes, the major for removals or renames.
CONTRACT_VERSION = "1.0"


class Options(BaseModel):
    #: false -> `message` comes back null and the caller writes its own words
    generate_text: bool = True
    #: "deterministic" needs no network; "llm" requires a configured adapter
    assess: str = "deterministic"
    #: derive the user signal from the latest turn when the caller left it NONE.
    #: Set false if the consumer classifies intent itself.
    detect_signal: bool = True


class TurnRequest(BaseModel):
    contract_version: str = CONTRACT_VERSION
    plan: InterviewPlan
    state: ConversationState
    options: Options = Field(default_factory=Options)


class Message(BaseModel):
    text: str
    move_type: MoveType | None = None
    #: concrete tokens lifted from the user's own last turn - grounding evidence
    grounded_on: list[str] = Field(default_factory=list)


class StateDelta(BaseModel):
    """The fields the caller should persist before the next call.

    Returned in full rather than as a patch: the component is stateless and the
    caller is the system of record, so an unambiguous overwrite beats a merge
    the consumer has to implement correctly."""

    topics: list[TopicRecord] = Field(default_factory=list)
    coverage: dict[str, bool] = Field(default_factory=dict)
    current_topic_id: str | None = None
    pattern_confirmed: bool = False


class Diagnostics(BaseModel):
    assessor: str = "deterministic"
    model: str | None = None
    latency_ms: int = 0
    usage: dict[str, int] = Field(default_factory=dict)


class TurnResponse(BaseModel):
    contract_version: str = CONTRACT_VERSION
    decision: Decision
    assessment: Assessment
    readiness: ArtifactReadiness
    message: Message | None = None
    artifact: dict | None = None
    state_delta: StateDelta = Field(default_factory=StateDelta)
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)
