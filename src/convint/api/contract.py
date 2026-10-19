"""The versioned wire contract - the only thing this component and its consumer
share. Neither repo imports the other's types.

MCP, HTTP, subprocess, and in-process callers all speak exactly these models.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..domain.artifact import ArtifactReadiness
from ..domain.crisis import ScreenResult
from ..domain.enums import MoveType
from ..domain.gate import Decision
from ..domain.plan import InterviewPlan
from ..domain.state import ConversationState, TopicRecord
from ..domain.sufficiency import Assessment

#: Bump the minor for additive changes, the major for removals or renames.
CONTRACT_VERSION = "1.3"


class Options(BaseModel):
    #: false -> `message` comes back null and the caller writes its own words
    generate_text: bool = True
    #: "server" = whatever the operator configured (CONVINT_ASSESSOR);
    #: "deterministic" forces the regex assessor for this call (free, offline);
    #: "llm" asks for the server's model-backed assessor, falling back to
    #: deterministic with a warning when the server has none. The caller never
    #: names a model - the operator controls cost.
    assess: Literal["server", "deterministic", "llm"] = "server"
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
    #: the assessor actually used this turn, e.g. "hybrid/haiku-4-5", or
    #: "deterministic" after a fallback
    assessor: str = "deterministic"
    #: generator / Read model id, when one was called
    model: str | None = None
    #: model id behind the assessor, when it is model-backed
    assessor_model: str | None = None
    latency_ms: int = 0
    #: tokens summed over every metered model call this turn (generation, Read,
    #: and the assessor when the server built it)
    usage: dict[str, int] = Field(default_factory=dict)
    #: USD for those calls; null when a called model's price is unknown
    cost_usd: float | None = None
    #: why anything fell back or was withheld; also startup degradations
    warnings: list[str] = Field(default_factory=list)
    #: true when any fallback/withholding happened or the server started degraded
    degraded: bool = False
    #: crisis screen of the last user turn (`@meddevkit/crisis-signals`, offline,
    #: unreviewed; it misses oblique language, so `none` does not mean safe).
    #: Null when there is no user turn. Reported whatever `signal` the caller
    #: sent; a `concern` or `crisis` level holds the turn only when convint
    #: detected the signal itself. Offsets are code-point indices.
    safety: ScreenResult | None = None


class TurnResponse(BaseModel):
    contract_version: str = CONTRACT_VERSION
    decision: Decision
    assessment: Assessment
    readiness: ArtifactReadiness
    message: Message | None = None
    artifact: dict | None = None
    state_delta: StateDelta = Field(default_factory=StateDelta)
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)
