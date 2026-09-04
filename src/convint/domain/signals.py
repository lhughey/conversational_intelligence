"""Deterministic detection of what a user's turn is DOING, as opposed to what it
contains.

Intent is orthogonal to sufficiency and is checked first by the gate, so a wrong
signal is more damaging than a wrong level: it bypasses the depth rule entirely.
Detection is therefore conservative - it returns NONE unless a pattern is clear,
and NONE simply falls through to the normal depth rules.

The distinction that matters most is CLOSING vs IMPATIENT. "That's enough" is
agency and is respected; "hurry up" is pressure and is not. Collapsing them is
the single most damaging error this module can make.
"""

from __future__ import annotations

import re

from .enums import UserSignal

_PATTERNS: list[tuple[UserSignal, list[str]]] = [
    # Adversarial first: it must never be reinterpreted as content.
    (UserSignal.ADVERSARIAL, [
        r"\bignore (?:your|all|previous) (?:instructions|prompt)",
        r"\bsystem\s*:", r"\bnew instructions\b", r"\byou are now\b",
        r"\brepeat your (?:system )?prompt\b", r"\bdisregard\b.*\binstructions\b",
        r"\bsay I (?:led|built|ran)\b.*\bwhen I didn'?t\b", r"\bmake (?:it|me) sound\b",
    ]),
    (UserSignal.OFF_TASK, [
        r"\bwrite me a cover letter\b", r"\bfix my resume\b", r"\bwhat should I do with my life\b",
        r"\bcan you just give me (?:advice|tips)\b",
    ]),
    (UserSignal.DISTRESS, [
        r"\bI can'?t (?:do this|go on|cope)\b", r"\bwant to (?:die|disappear)\b",
        r"\bfalling apart\b", r"\bcan'?t stop crying\b",
    ]),
    # Closing: they are DONE. Agency, respected.
    (UserSignal.CLOSING, [
        r"^\s*no[.,!]?\s*(?:that'?s (?:it|all|enough)|that covers it)",
        r"\bthat'?s enough\b", r"\bthat covers it\b", r"\bwe found it\b",
        r"\bplease write it up\b", r"\bI'?m done\b", r"\bthat'?s all\b",
    ]),
    # Impatient: they want it FASTER. Pressure, not permission.
    (UserSignal.IMPATIENT, [
        r"\bcan we (?:move|skip|speed)\b", r"\bget to the (?:point|synthesis)\b",
        r"\bgive me the (?:synthesis|answer|summary) now\b", r"\bwhere are you going with this\b",
        r"\bhow long (?:is this|does this take)\b", r"\bcan you just\b.*\bnow\b",
        r"\bI already (?:know|told you)\b",
    ]),
    (UserSignal.ACKNOWLEDGMENT_ONLY, [
        r"^\s*(?:ok|okay)\b[.,!]*\s*(?:show me|go on|sure|continue|i'?m ready)?[.,!]*\s*$",
        r"^\s*(?:got it|understood|makes sense|fair enough)[.,!]*\s*$",
    ]),
    (UserSignal.DEFLECTION, [
        r"\bI don'?t (?:really |actually |quite )?(?:know|remember|think)\b",
        r"\bnothing (?:weird|special|really)\b",
        r"\bnot (?:sure|really)\b", r"\bno idea\b", r"\bcan'?t think of\b",
    ]),
]


def detect_signal(text: str) -> UserSignal:
    """Best-effort intent detection. Returns NONE when nothing is clear."""
    stripped = text.strip()
    for signal, patterns in _PATTERNS:
        for pattern in patterns:
            if re.search(pattern, stripped, flags=re.IGNORECASE):
                return signal
    return UserSignal.NONE
