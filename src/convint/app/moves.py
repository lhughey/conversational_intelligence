"""Deterministic move selection.

Variety comes from choosing among *kinds* of question, not from sampling
randomness - which matters here because sampling is not tunable on the current
Opus/Sonnet models, and because a different kind of question is what actually
reads as human.

Selection targets whichever narrative component the topic is still missing, so
the follow-up is aimed rather than generic.
"""

from __future__ import annotations

from ..domain.enums import Action, MoveType, SubAction
from ..domain.gate import Decision
from ..domain.sufficiency import SufficiencyComponents

#: asked in the order a story is usually missing pieces
_COMPONENT_MOVES: list[tuple[str, MoveType]] = [
    ("scene", MoveType.ASK_FOR_SCENE),
    ("stakes", MoveType.ASK_WHAT_WAS_AT_STAKE),
    ("action", MoveType.ASK_WHAT_THEY_DID),
    ("outcome", MoveType.ASK_WHAT_SURPRISED),
]


def select_move(
    decision: Decision,
    components: SufficiencyComponents,
    *,
    has_earlier_material: bool = False,
    exclude: set[MoveType] | None = None,
) -> MoveType | None:
    """Return the move for a follow-up, or None when no question is being asked."""
    if decision.action is not Action.FOLLOW_UP:
        return None

    exclude = exclude or set()

    if decision.sub_action is SubAction.HOLD:
        return MoveType.REFLECT_AND_CHECK

    if decision.sub_action is SubAction.REDIRECT:
        # Thin answers get a smaller, more concrete access point - never a
        # bigger or more abstract reframe.
        return MoveType.ASK_FOR_SCENE

    ordered: list[MoveType] = [
        move for field, move in _COMPONENT_MOVES if not getattr(components, field)
    ]
    if not components.reflection:
        ordered.append(MoveType.REFLECT_AND_CHECK)
    if has_earlier_material:
        ordered.append(MoveType.CONTRAST_WITH_EARLIER)
    ordered.append(MoveType.REFLECT_AND_CHECK)

    for move in ordered:
        if move not in exclude:
            return move
    return ordered[0] if ordered else MoveType.REFLECT_AND_CHECK
