"""Small, dependency-free text utilities.

Deliberately not spaCy or NLTK: a model file whose version silently changes a
metric is exactly the hidden variable this component is built to avoid. Forty
lines of inspectable code beats a pinned model artifact here.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")

STOPWORDS = frozenset("""
a about actually after all also am an and any are around as at back be because been
before being but by can cant could did didnt do dont down each even ever every for
from get got had has have he her here hers him his how i id if ill im in into is it
its ive just kind know like ll me more most much my no not now of off oh ok on one
only or other our out over really right said say see she should so some something
such than that thats the their them then there these they thing things think this
those through to too up us very was we well were what when where which while who
why will with would yeah yes you your youre
""".split())


def tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD.finditer(text)]


def content_tokens(text: str) -> list[str]:
    """Words carrying topical content: no stopwords, nothing trivially short."""
    return [t for t in tokens(text) if t not in STOPWORDS and len(t) > 2]


def grounding_overlap(candidate: str, source: str, exclude: str = "") -> list[str]:
    """Content words in `candidate` lifted from `source`.

    `exclude` removes credit for words the interviewer already used itself or
    that came from a scripted question - otherwise a model scores as "grounded"
    for echoing its own prior turn.
    """
    excluded = set(content_tokens(exclude))
    src = set(content_tokens(source)) - excluded
    seen, out = set(), []
    for t in content_tokens(candidate):
        if t in src and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def quoted_span(candidate: str, source: str, min_run: int = 2) -> str | None:
    """Longest run of >= `min_run` consecutive content words shared with `source`.

    A stronger grounding signal than bag-of-words overlap: it shows the phrase
    was carried over, not coincidentally re-used.
    """
    cand, src = content_tokens(candidate), content_tokens(source)
    if not cand or not src:
        return None
    src_joined = " " + " ".join(src) + " "
    best = None
    for i in range(len(cand)):
        for j in range(len(cand), i + min_run - 1, -1):
            run = cand[i:j]
            if len(run) < min_run:
                break
            phrase = " ".join(run)
            if f" {phrase} " in src_joined and (best is None or len(run) > len(best.split())):
                best = phrase
                break
    return best


def question_count(text: str) -> int:
    return text.count("?")


def ends_with_question(text: str) -> bool:
    return text.rstrip().endswith("?")
