"""Build turn-decision items by replaying the corpus, and derive WEAK labels.

Two honest limitations, stated here because they bound everything downstream:

1. The goldens contain no assistant turns, so the conversational context is the
   user side plus reconstructed state (budget, sufficiency, signal, coverage).
   That is enough to evaluate the GATE, which reads state rather than prose. It
   is not enough to evaluate generation.

2. The labels are WEAK. They are inferred from the transcript's own next user
   turn - what the author implicitly assumed the interviewer had asked - not
   from independent human judgement. That is a real signal (the author wrote
   turn N+1 to answer something specific) but it is not ground truth. Every
   label is marked `source="weak"` and should be adjudicated before any number
   derived from it is quoted as an accuracy.
"""

from __future__ import annotations

import json
import pathlib

from ..adapters.assessor_deterministic import DeterministicAssessor
from ..domain.enums import Action, Ownership, Specificity, UserSignal
from ..domain.signals import detect_signal
from ..domain.sufficiency import SufficiencyComponents
from ..domain.text import content_tokens
from .schema import Item, Label

REPO = pathlib.Path(__file__).resolve().parents[3]
GOLDENS = REPO / "docs" / "golden-transcripts"
OUT = REPO / "data" / "turn_decisions"

FLOOR, CEILING = 1, 3

#: lexical markers that a turn has moved to a different life domain
_ERA_MARKERS = {
    "early_life": {"kid", "child", "childhood", "young", "school", "college", "parents", "grew"},
    "career": {"career", "job", "role", "work", "company", "team", "manager", "startup"},
    "outside": {"outside", "hobby", "weekend", "garden", "write", "writing", "volunteer"},
}


def segment_threads(turns: list[str]) -> list[int]:
    """Assign each turn a thread index, INDEPENDENTLY of any action label.

    Independence is the point. Previously the weak label decided whether the
    follow-up counter reset, the counter went into the state the gate reads,
    and the gate's answer was scored against that same weak label - a loop. In
    practice the counter stopped meaning "follow-ups spent on this topic" and
    became "turns since the conversation began": 8 resets across 92 turns, one
    walk reaching 13, and 29 items sitting above the ceiling as pure artifact.

    A thread here is a run of turns in the same life domain, with unmarked
    turns inheriting the domain of the turn before. Lexical-overlap rules were
    tried and rejected: they cut a new thread almost every turn (mean length
    1.2) because adjacent answers in these interviews genuinely share few
    words - each one answers a different question. Domain-stickiness gives 24
    threads at a mean length of 3.8, which matches how these walks actually
    move: early life, then career, then outside work.
    """
    threads: list[int] = []
    current = 0
    last_era: str | None = None
    for i, text in enumerate(turns):
        era = _era(text) or last_era
        if i > 0 and era is not None and last_era is not None and era != last_era:
            current += 1
        threads.append(current)
        if era is not None:
            last_era = era
    return threads


def _era(text: str) -> str | None:
    toks = set(content_tokens(text))
    hits = {era: len(toks & markers) for era, markers in _ERA_MARKERS.items()}
    best = max(hits, key=hits.get)
    return best if hits[best] > 0 else None


def _weak_label(turns: list[str], i: int, signal: UserSignal) -> Label:
    """Infer what the interviewer must have done, from what the user said next."""
    item_id = ""  # filled by the caller

    if signal in (UserSignal.ADVERSARIAL, UserSignal.OFF_TASK):
        return Label(item_id=item_id, action=Action.REFUSE_AND_CONTINUE,
                     forbidden=[Action.ADVANCE, Action.SYNTHESIZE],
                     rationale="adversarial input", source="weak", confidence="high")

    if signal is UserSignal.CLOSING or i == len(turns) - 1:
        return Label(item_id=item_id, action=Action.SYNTHESIZE,
                     acceptable=[Action.ADVANCE],
                     rationale="closing signal or end of walk", source="weak")

    current, nxt = turns[i], turns[i + 1]
    overlap = len(set(content_tokens(current)) & set(content_tokens(nxt)))
    era_now, era_next = _era(current), _era(nxt)

    # A clear era change in the next turn means the interviewer moved on.
    if era_now and era_next and era_now != era_next:
        # Domain shift AND no lexical continuity is strong evidence the
        # interviewer advanced. Marking FOLLOW_UP forbidden here is what makes
        # `stall_rate` computable at all - without at least some strict
        # must-advance items the mirror metric has an empty denominator and a
        # policy that always follows up looks flawless.
        strict = overlap < 2
        return Label(
            item_id=item_id, action=Action.ADVANCE,
            acceptable=[] if strict else [Action.FOLLOW_UP],
            forbidden=[Action.FOLLOW_UP] if strict else [],
            rationale=(f"next turn shifts domain {era_now} -> {era_next}"
                       f" (overlap {overlap})"),
            source="weak", confidence="medium" if strict else "low")

    # Strong lexical continuity means the next turn answers a deepening question.
    if overlap >= 3:
        return Label(item_id=item_id, action=Action.FOLLOW_UP,
                     acceptable=[],
                     forbidden=[Action.SYNTHESIZE],
                     rationale=f"next turn continues the same material (overlap {overlap})",
                     source="weak")

    return Label(item_id=item_id, action=Action.FOLLOW_UP,
                 acceptable=[Action.ADVANCE],
                 rationale="ambiguous: no strong continuity or domain shift",
                 source="weak")


def build(assessor=None) -> tuple[list[Item], list[Label]]:
    assessor = assessor or DeterministicAssessor()
    items: list[Item] = []
    labels: list[Label] = []

    for path in sorted(GOLDENS.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        turns = data["userTurns"]

        components = SufficiencyComponents()
        followups = 0
        spec, own = Specificity.S0, Ownership.O0
        threads = segment_threads(turns)

        for i, text in enumerate(turns):
            # Thread boundaries come from the text, never from the label.
            if i > 0 and threads[i] != threads[i - 1]:
                followups = 0
                components = SufficiencyComponents()
                spec, own = Specificity.S0, Ownership.O0
            assessment = assessor.assess(text, components)
            components, spec, own = (
                assessment.components, assessment.specificity, assessment.ownership
            )
            signal = detect_signal(text)
            item_id = f"{path.stem}#{i}"

            items.append(Item(
                item_id=item_id, transcript=path.stem, turn_index=i,
                user_turns=turns[: i + 1], text=text,
                followups_used=followups, floor=FLOOR, ceiling=CEILING,
                specificity=spec, ownership=own, signal=signal,
                stage_covered=False, text_prefix=text[:60],
            ))

            label = _weak_label(turns, i, signal)
            label.item_id = item_id
            labels.append(label)

            # Only follow-ups consume budget; the reset is handled above, by
            # the text-derived thread boundary rather than by this label.
            if label.action is Action.FOLLOW_UP:
                followups += 1

    return items, labels


def write(items: list[Item], labels: list[Label],
          prefix: str = "") -> tuple[pathlib.Path, pathlib.Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    ip, lp = OUT / f"{prefix}items.jsonl", OUT / f"{prefix}labels.jsonl"
    ip.write_text("\n".join(i.model_dump_json() for i in items) + "\n", encoding="utf-8")
    lp.write_text("\n".join(l.model_dump_json() for l in labels) + "\n", encoding="utf-8")
    return ip, lp


def load(prefix: str = "") -> tuple[list[Item], list[Label]]:
    ip, lp = OUT / f"{prefix}items.jsonl", OUT / f"{prefix}labels.jsonl"
    items = [Item.model_validate_json(l) for l in ip.read_text(encoding="utf-8").splitlines() if l.strip()]
    labels = [Label.model_validate_json(l) for l in lp.read_text(encoding="utf-8").splitlines() if l.strip()]
    return items, labels


def build_all() -> dict[str, tuple[list[Item], list[Label]]]:
    """Both splits, kept separate because their label provenance differs.

    `corpus` labels are WEAK (inferred from the transcript's next turn).
    `synth` labels are SPEC (derived from the written rule).
    Neither is human-adjudicated; mixing them would hide that.
    """
    from .synth import build_from_banks

    return {"corpus": build(), "synth": build_from_banks()}
