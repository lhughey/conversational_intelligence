"""Persona answer banks: the authored source the corpus is generated FROM.

A transcript is a recording of one path. It cannot produce a case where
advancing is correct, cannot hold everything fixed while varying one thing, and
cannot answer a question it was not written for. Those three limits are why a
transcript-derived label set comes out skewed toward "follow up".

A bank stores answers as RUNGS on a topic - S1, S2, S3, O2 - served one per
question asked. That buys three things a transcript cannot:

  * Gold sufficiency is DEFINITIONAL, not inferred. A rung authored as an
    episode is an episode; there is no weak-label problem on that axis.
  * Minimal pairs fall out mechanically: same prefix, same budget, swap only
    the final rung, and the correct action changes for exactly one reason.
  * Must-advance cases exist by construction - serve a rich rung once the floor
    is met and moving on becomes the right answer.

Rungs also WITHHOLD: a topic serves S1 before S2 before S3. Handing over the
episode on the first ask would make "draw it out, do not hand it over"
unmeasurable.
"""

from __future__ import annotations

import json
import pathlib

from pydantic import BaseModel, Field

from ..domain.enums import Ownership, Specificity

BANKS = pathlib.Path(__file__).resolve().parents[3] / "data" / "personas"


class Rung(BaseModel):
    """One answer at one depth, with its sufficiency stated rather than guessed."""

    rung: str                      # "S1" | "S2" | "S3" | "O2"
    text: str
    specificity: Specificity
    ownership: Ownership
    #: rungs that must already have been served for this one to make sense.
    #: This is what stops an episode being served with no antecedent - the
    #: defect in the original questions.json, now a schema invariant.
    requires_prior: list[str] = Field(default_factory=list)
    #: where this text came from, if it is lifted from the corpus
    source: str | None = None


class BankTopic(BaseModel):
    topic_id: str
    stage: str
    #: question intents this topic answers, for intent-keyed serving
    intents: list[str] = Field(default_factory=list)
    rungs: list[Rung] = Field(default_factory=list)
    exhausted_response: str = "I think that's the whole of it."

    def rung(self, name: str) -> Rung | None:
        return next((r for r in self.rungs if r.rung == name), None)


class Persona(BaseModel):
    persona_id: str
    display_name: str
    one_line: str = ""
    synthetic: bool = True
    topics: list[BankTopic] = Field(default_factory=list)

    def topic(self, topic_id: str) -> BankTopic | None:
        return next((t for t in self.topics if t.topic_id == topic_id), None)


def load_personas(directory: pathlib.Path | None = None) -> list[Persona]:
    directory = directory or BANKS
    return [
        Persona.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("*.persona.json"))
    ]


def save(persona: Persona, directory: pathlib.Path | None = None) -> pathlib.Path:
    directory = directory or BANKS
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{persona.persona_id}.persona.json"
    path.write_text(json.dumps(persona.model_dump(mode="json"), indent=2) + "\n",
                    encoding="utf-8")
    return path
