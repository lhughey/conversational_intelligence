"""Mechanical truth-floor checks over an emitted Read.

The Read prompt forbids inventing quotes, numbers, employers, dates, job titles
and events. A model asked nicely will still occasionally do it, so whatever can
be checked mechanically is checked here, after generation, against the user's
own turns only (never the interviewer's).

What is checked:

  quotes   Every span inside double quotes ("..." or curly “...”, also «...»)
           or clearly-delimited single quotes ('...' or ‘...’) of at least
           `MIN_QUOTE_CHARS` characters must appear verbatim (case-, whitespace-,
           quote-style- and dash-style-insensitive) in a user turn. An ellipsis
           inside a quote splits it into fragments that must each appear.
  numbers  Every number the Read states - digits, percentages, currency,
           magnitudes ("$2M", "2 million"), years, and number words from three
           up ("three", "twelve-state", "a dozen", "two hundred") - must have
           the same value somewhere in the user's turns, in either form
           ("12" <-> "twelve", "300%" <-> "300 percent"). A percentage must be
           backed by a percentage.

What is deliberately NOT checked (documented limits, not oversights):

  - "one" and "two" as words: they are pronouns and idioms far more often than
    claims ("no one", "the one who", "two sides"); a real cached Read already
    says "a word meaning two different things" where the user never said
    "two". Digits "1" and "2" are still checked.
  - ordinals and fractions as words ("first", "third", "half", "a third"),
    vague plurals ("hundreds of", "dozens").
  - quoted spans shorter than `MIN_QUOTE_CHARS`: these are overwhelmingly
    scare-quoted terms ("done", "fine"), where withholding the whole Read would
    cost far more than it protects.
  - intent: presence-based only. If the user said "just say 300%" and then
    disowned it, "300%" still counts as theirs. The prompt rule covers that.
  - proper nouns (employers, places, titles). TODO: a capitalised-token check
    was considered but not implemented - Read headlines are often Title Case
    and pattern names are capitalised, and there is only one real Read on disk
    to measure false positives against. Revisit once a sample of real Reads
    exists to calibrate on.
"""

from __future__ import annotations

import re
from typing import Iterator, Literal

from pydantic import BaseModel

#: Shorter quoted spans are terms, not claims (see module docstring).
MIN_QUOTE_CHARS = 6

#: Number words below this value are not checked in the Read (see docstring).
MIN_WORD_NUMBER = 3


class TruthFloorIssue(BaseModel):
    """One unsupported span in an emitted Read."""

    kind: Literal["quote", "number"]
    #: path to the field it was found in, e.g. "brings" or "items[0].text"
    field: str
    #: the span as emitted
    span: str


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

_CHAR_MAP = str.maketrans({
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "«": '"', "»": '"', "″": '"',
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-",
    " ": " ", " ": " ",
})


def normalize(text: str) -> str:
    """Fold typographic variants to ASCII: curly quotes and apostrophes,
    dashes, non-breaking spaces, the ellipsis character."""
    return text.translate(_CHAR_MAP).replace("…", "...")


def _match_form(text: str) -> str:
    """The form both sides are compared in: normalised, lower-cased, a dash
    spaced the same whether or not it was written with spaces, whitespace
    collapsed."""
    text = normalize(text).lower()
    text = re.sub(r"\s*-\s*", " - ", text)
    return re.sub(r"\s+", " ", text).strip()


def _walk_strings(value, path: str = "") -> Iterator[tuple[str, str]]:
    """Every string in an artifact, with its field path. Nested objects and
    lists are walked so a caller-supplied schema cannot route around the
    check."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _walk_strings(item, f"{path}[{i}]")


# --------------------------------------------------------------------------
# Quotes
# --------------------------------------------------------------------------

#: Sequential pairing: quotes are consumed left to right, so the text BETWEEN
#: two quoted spans is never mistaken for a quote.
_DOUBLE_QUOTED = re.compile(r'"([^"]*)"')

#: Contractions that begin with an apostrophe and would otherwise look like an
#: opening single quote.
_ELISIONS = r"(?:em|cause|cos|til|tis|twas|n|bout|round)\b"

#: A single-quoted span. The opening quote must sit at a word boundary (start,
#: whitespace or opening punctuation before it, a letter after it) so the
#: apostrophes in "don't" and "parents' house" never open a span; the closing
#: quote must follow a non-space and be followed by the end, whitespace or
#: punctuation, so "don't" never closes one either.
_SINGLE_QUOTED = re.compile(
    r"(?<![^\s(\[{\"-])'(?!" + _ELISIONS + r")(?=[A-Za-z])"
    r"([^\n]+?)(?<=\S)'(?=$|[\s.,;:!?)\]}\"-])",
    re.IGNORECASE,
)


def extract_quotes(text: str) -> list[str]:
    """Quoted spans of at least `MIN_QUOTE_CHARS` characters, in either quote
    style, as written (after typographic normalisation)."""
    text = normalize(text)
    spans = _DOUBLE_QUOTED.findall(text)
    # Single quotes are looked for outside double-quoted spans only; a single
    # quote nested in a double-quoted span is covered by the outer span.
    outside = _DOUBLE_QUOTED.sub(" ", text)
    spans += _SINGLE_QUOTED.findall(outside)
    return [s for s in spans if len(s.strip()) >= MIN_QUOTE_CHARS]


def _quote_in_source(quote: str, source: str) -> bool:
    fragments = [_match_form(f).strip(" .,;:!?'\"-") for f in normalize(quote).split("...")]
    fragments = [f for f in fragments if f]
    return all(f in source for f in fragments)


def unsupported_quotes(artifact: dict, user_text: str) -> list[TruthFloorIssue]:
    source = _match_form(user_text)
    issues = []
    for field, value in _walk_strings(artifact):
        for quote in extract_quotes(value):
            if not _quote_in_source(quote, source):
                issues.append(TruthFloorIssue(kind="quote", field=field, span=quote))
    return issues


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------

_LETTER_MAGNITUDE = {"k": 1e3, "m": 1e6, "mm": 1e6, "b": 1e9, "bn": 1e9}
_WORD_MAGNITUDE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}

_DIGITS = re.compile(
    r"(?<![\w.])(?P<cur>[$£€])?\s?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:(?P<lmag>k|mm|m|bn|b)\b|\s?(?P<wmag>thousand|million|billion|trillion)\b)?"
    r"(?P<pct>\s?%|\s?(?:percent|per\s?cent)\b)?",
    re.IGNORECASE,
)

#: A list marker at the start of a line ("1. ", "2) ") is layout, not a claim.
_LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s")

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "dozen": 12, **_WORD_MAGNITUDE}
_NUMBER_WORD = re.compile(
    r"\b(" + "|".join(sorted([*_UNITS, *_TENS, *_SCALES, "a"], key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_PERCENT_AFTER = re.compile(r"\s?(?:%|percent\b|per\s?cent\b)", re.IGNORECASE)


class _Mention(BaseModel):
    span: str
    value: float
    percent: bool = False
    #: the unscaled value, for "5m" read as five of something
    base: float | None = None
    from_words: bool = False


def _key(value: float) -> float:
    return round(value, 6)


def _digit_mentions(text: str) -> tuple[list[_Mention], list[tuple[int, int]]]:
    out, spans = [], []
    for m in _DIGITS.finditer(text):
        spans.append(m.span())
        base = float(m.group("num").replace(",", ""))
        mag = m.group("lmag") or m.group("wmag")
        scale = 1.0
        if mag:
            mag = mag.lower()
            scale = _LETTER_MAGNITUDE.get(mag) or _WORD_MAGNITUDE[mag]
        out.append(_Mention(
            span=m.group(0).strip(), value=base * scale, base=base,
            percent=bool(m.group("pct")),
        ))
    return out, spans


def _combines(prev: str, nxt: str) -> bool:
    """Whether `nxt` continues the number `prev` started ("twenty-five",
    "three hundred", "hundred twenty") rather than starting a new one
    ("two three-hour sessions" is two numbers, not five)."""
    if nxt in _SCALES:
        return True
    if prev in _TENS:
        return nxt in _UNITS and 1 <= _UNITS[nxt] <= 9
    if prev in _SCALES:
        return nxt in _UNITS or nxt in _TENS
    return False


def _word_value(words: list[str]) -> float:
    total, current = 0.0, 0.0
    for w in words:
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w in ("hundred", "dozen"):
            current = (current or 1) * _SCALES[w]
        elif w in _WORD_MAGNITUDE:
            total += (current or 1) * _WORD_MAGNITUDE[w]
            current = 0
        # "a" contributes only through the `or 1` above
    return total + current


def _word_mentions(text: str, taken: list[tuple[int, int]]) -> list[_Mention]:
    """Number words, skipping any already read as part of a digit mention
    (the "million" in "2 million")."""
    tokens = [
        (m.group(1).lower(), m.start(), m.end()) for m in _NUMBER_WORD.finditer(text)
        if not any(a <= m.start() < b for a, b in taken)
    ]
    groups: list[list[tuple[str, int, int]]] = []
    for tok in tokens:
        if groups:
            prev = groups[-1][-1]
            gap = text[prev[2]:tok[1]]
            if gap in (" ", "-") and (
                (prev[0] == "a" and tok[0] in _SCALES) or
                (prev[0] != "a" and _combines(prev[0], tok[0]))
            ):
                groups[-1].append(tok)
                continue
        groups.append([tok])

    out = []
    for group in groups:
        words = [w for w, _, _ in group]
        if words == ["a"]:
            continue
        start, end = group[0][1], group[-1][2]
        pct = _PERCENT_AFTER.match(text, end)
        out.append(_Mention(
            span=text[start:pct.end() if pct else end], value=_word_value(words),
            percent=bool(pct), from_words=True,
        ))
    return out


def number_mentions(text: str) -> list[_Mention]:
    text = _LIST_MARKER.sub(" ", normalize(text))
    digits, taken = _digit_mentions(text)
    return digits + _word_mentions(text, taken)


def unsupported_numbers(artifact: dict, user_text: str) -> list[TruthFloorIssue]:
    """Numbers the Read states that the user never did, in any form."""
    supported: set[float] = set()
    supported_pct: set[float] = set()
    for m in number_mentions(user_text):
        values = {_key(m.value)} | ({_key(m.base)} if m.base is not None else set())
        supported |= values
        if m.percent:
            supported_pct |= values

    issues = []
    for field, value in _walk_strings(artifact):
        for m in number_mentions(value):
            if m.from_words and m.value < MIN_WORD_NUMBER:
                continue
            pool = supported_pct if m.percent else supported
            if _key(m.value) not in pool:
                issues.append(TruthFloorIssue(kind="number", field=field, span=m.span))
    return issues


def check_truth_floor(artifact: dict, user_text: str) -> list[TruthFloorIssue]:
    """Every mechanically-checkable truth-floor issue in an emitted Read."""
    return unsupported_quotes(artifact, user_text) + unsupported_numbers(artifact, user_text)
