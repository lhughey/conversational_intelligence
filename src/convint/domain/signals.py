"""Deterministic detection of what a user's turn is DOING, as opposed to what it
contains.

Intent is orthogonal to sufficiency and is checked first by the gate, so a wrong
signal is more damaging than a wrong level: it bypasses the depth rule entirely.
Detection is therefore conservative - it returns NONE unless a pattern is clear,
and NONE simply falls through to the normal depth rules.

The distinction that matters most is CLOSING vs IMPATIENT. "That's enough" is
agency and is respected; "hurry up" is pressure and is not. Collapsing them is
the single most damaging error this module can make.

Distress is the exception to "conservative": it comes from the crisis screen
(`domain/crisis`, a port of `@meddevkit/crisis-signals`), is checked before
everything else, and fires on `concern` as well as `crisis`, because a missed
crisis costs more than a held turn. The screen's full result is reported to the
caller as `diagnostics.safety`; escalation stays the caller's job.
"""

from __future__ import annotations

import re

from .crisis import ScreenResult, screen_text
from .enums import UserSignal

#: screen levels that hold the interview as DISTRESS
DISTRESS_LEVELS = frozenset({"concern", "crisis"})

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


def detect_signal(text: str, screen: ScreenResult | None = None) -> UserSignal:
    """Best-effort intent detection. Returns NONE when nothing is clear.

    `screen` is the crisis screen of `text` when the caller already ran it.
    """
    if (screen or screen_text(text)).level in DISTRESS_LEVELS:
        return UserSignal.DISTRESS
    stripped = text.strip()
    for signal, patterns in _PATTERNS:
        for pattern in patterns:
            if re.search(pattern, stripped, flags=re.IGNORECASE):
                return signal
    return UserSignal.NONE
