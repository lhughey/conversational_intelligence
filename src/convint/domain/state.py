"""Conversation state. The component is stateless; the caller owns this object
and passes it whole on every call.

Keeping the component stateless is what lets MCP, HTTP, and subprocess behave
identically - a server-side session would bind the component to one transport.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import Ownership, Specificity, UserSignal
from .sufficiency import SufficiencyComponents


class Turn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class TopicRecord(BaseModel):
    """Everything the gate needs to know about one topic under discussion."""

    topic_id: str
    stage: str

    #: follow-ups the interviewer has already spent on THIS topic
    followups_used: int = 0
    #: verbatim questions already asked on this topic - enables redundancy detection
    asked_questions: list[str] = Field(default_factory=list)

    #: accumulated across every user turn on this topic
    components: SufficiencyComponents = Field(default_factory=SufficiencyComponents)
    specificity: Specificity = Specificity.S0
    ownership: Ownership = Ownership.O0

    closed: bool = False

    def has_asked(self, question: str) -> bool:
        """Normalized containment check - catches the re-ask failure mode."""
        norm = " ".join(question.lower().split())
        return any(" ".join(q.lower().split()) == norm for q in self.asked_questions)


class ConversationState(BaseModel):
    turns: list[Turn] = Field(default_factory=list)
    topics: list[TopicRecord] = Field(default_factory=list)
    current_topic_id: str | None = None

    #: stage_id -> whether the stage has been covered
    coverage: dict[str, bool] = Field(default_factory=dict)
    signal: UserSignal = UserSignal.NONE

    #: set once the user has confirmed the named pattern in their own words
    pattern_confirmed: bool = False

    def topic(self, topic_id: str) -> TopicRecord | None:
        return next((t for t in self.topics if t.topic_id == topic_id), None)

    def current_topic(self) -> TopicRecord | None:
        if self.current_topic_id is None:
            return None
        return self.topic(self.current_topic_id)

    def last_user_turn(self) -> Turn | None:
        return next((t for t in reversed(self.turns) if t.role == "user"), None)
