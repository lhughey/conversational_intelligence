"""Schemas for the turn-decision dataset.

Items and labels are deliberately SEPARATE files. That lets items be
regenerated from the corpus without touching labels, lets inter-annotator
agreement be computed, and structurally prevents a label from leaking into a
prompt.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain.enums import Action, Ownership, Specificity, SubAction, UserSignal


class Item(BaseModel):
    """One decision point: everything the gate can see, and nothing it cannot."""

    item_id: str
    transcript: str
    turn_index: int

    #: the user turns up to and including the one being decided on
    user_turns: list[str] = Field(default_factory=list)
    #: the turn under decision, duplicated for readability
    text: str

    # reconstructed state at this point in the walk
    followups_used: int = 0
    floor: int = 1
    ceiling: int = 3
    specificity: Specificity = Specificity.S0
    ownership: Ownership = Ownership.O0
    signal: UserSignal = UserSignal.NONE
    stage_covered: bool = False

    #: guards against silent re-scoring if a transcript is edited
    text_prefix: str = ""


class Label(BaseModel):
    item_id: str
    action: Action
    #: additional actions that are also defensible; scored as correct
    acceptable: list[Action] = Field(default_factory=list)
    #: actions that would be wrong; used for the failure-rate metrics
    forbidden: list[Action] = Field(default_factory=list)
    sub_action: SubAction | None = None
    rationale: str = ""
    #: "weak" = derived from the transcript's own next turn; "human" = adjudicated
    source: str = "weak"
    confidence: str = "low"

    def is_correct(self, predicted: Action) -> bool:
        return predicted is self.action or predicted in self.acceptable
