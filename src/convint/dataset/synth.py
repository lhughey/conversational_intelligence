"""Generate balanced turn-decision items from persona banks.

Why this exists: the transcript-derived set came out 72/92 `follow_up`, with a
must-advance denominator of 2. That is a shape problem - every golden was
authored to punish premature advance and none to punish stalling - so the set
cannot distinguish a good gate from a policy that never moves on.

Generating from banks fixes it structurally. Sufficiency per rung is authored,
so it is definitional rather than inferred; budget states are enumerated rather
than whatever the transcript happened to do; and MINIMAL PAIRS hold everything
fixed except the final rung, so when the correct action changes there is exactly
one reason why.

On label provenance, stated plainly: labels here are `source="spec"` - derived
from the written decision rule, not from independent human judgement. They make
CONFORMANCE and COVERAGE measurable. They are NOT evidence that the rule itself
is right; only human adjudication produces that, which is what the `label`
command exists for.
"""

from __future__ import annotations

import itertools

from ..domain.enums import Action, Ownership, Specificity, UserSignal
from .bank import Persona, load_personas
from .schema import Item, Label

FLOOR, CEILING = 1, 3
BUDGET_STATES = [0, 1, 2, 3]


def spec_action(
    specificity: Specificity, ownership: Ownership,
    followups_used: int, floor: int, ceiling: int,
) -> tuple[Action, str]:
    """The decision rule as SPECIFICATION, written independently of gate.py.

    Deliberately a separate implementation. Agreement between this and
    `gate.decide` is a conformance property worth testing; sharing one function
    would make that test vacuous.
    """
    if followups_used >= ceiling:
        return Action.ADVANCE, "ceiling reached"
    if followups_used < floor:
        return Action.FOLLOW_UP, "floor not met"
    if specificity.rank >= Specificity.S3.rank and ownership.rank >= Ownership.O1.rank:
        return Action.ADVANCE, "episode with ownership"
    if specificity.rank >= Specificity.S2.rank and ownership is Ownership.O2:
        return Action.ADVANCE, "user did the meaning-making"
    return Action.FOLLOW_UP, "not yet an owned episode"


def build_from_banks(personas: list[Persona] | None = None) -> tuple[list[Item], list[Label]]:
    personas = personas if personas is not None else load_personas()
    items: list[Item] = []
    labels: list[Label] = []

    for persona in personas:
        for topic in persona.topics:
            for rung, used in itertools.product(topic.rungs, BUDGET_STATES):
                # Serve the rungs this one depends on, so the prefix is coherent.
                prior = [
                    r.text for name in rung.requires_prior
                    if (r := topic.rung(name)) is not None
                ]
                turns = prior + [rung.text]

                item_id = f"{persona.persona_id}/{topic.topic_id}#{rung.rung}@{used}"
                items.append(Item(
                    item_id=item_id, transcript=f"bank:{persona.persona_id}",
                    turn_index=len(turns) - 1,
                    user_turns=turns, text=rung.text,
                    followups_used=used, floor=FLOOR, ceiling=CEILING,
                    specificity=rung.specificity, ownership=rung.ownership,
                    signal=UserSignal.NONE, stage_covered=False,
                    text_prefix=rung.text[:60],
                ))

                action, why = spec_action(
                    rung.specificity, rung.ownership, used, FLOOR, CEILING
                )
                labels.append(Label(
                    item_id=item_id, action=action,
                    forbidden=[Action.FOLLOW_UP] if action is Action.ADVANCE
                              else [Action.ADVANCE, Action.SYNTHESIZE],
                    rationale=f"{why} (S{rung.specificity.rank}/O{rung.ownership.rank}, "
                              f"{used} of {FLOOR}-{CEILING} follow-ups spent)",
                    source="spec", confidence="high",
                ))

    return items, labels


def minimal_pairs(items: list[Item], labels: list[Label]) -> list[tuple[str, str]]:
    """Pairs differing ONLY in the final rung, where the correct action differs.

    These are the diagnostically valuable items: any policy that gets a pair
    wrong is not reading sufficiency, whatever its overall accuracy looks like.
    """
    by_id = {l.item_id: l for l in labels}
    grouped: dict[tuple[str, int], list[Item]] = {}
    for item in items:
        topic = item.item_id.split("#")[0]
        grouped.setdefault((topic, item.followups_used), []).append(item)

    pairs = []
    for group in grouped.values():
        for a, b in itertools.combinations(group, 2):
            if by_id[a.item_id].action is not by_id[b.item_id].action:
                pairs.append((a.item_id, b.item_id))
    return pairs
