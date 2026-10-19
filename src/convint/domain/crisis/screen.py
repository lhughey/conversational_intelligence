"""Python port of `@meddevkit/crisis-signals` `screenText` (pattern data 0.2.0).

Keyword-and-context screen for first-person crisis language. It is NOT a
diagnostic or risk-assessment tool, it misses oblique language (about half of
crisis statements on text it was not written against), and it must never be
the only safeguard. convint only reports the result and holds the interview;
escalation belongs to the caller.

All phrases live in `data/crisis.patterns.json`, vendored unchanged from the
npm package (see `data/NOTICE`). This module mirrors the package's engine
(`src/{data,regex,text,match,scope,gate,resolve,screen}.ts`) rule for rule;
`tests/test_crisis_parity.py` pins it to the JavaScript output.

One deliberate difference: offsets are Python string indices (code points),
not UTF-16 code units, so `text[start_offset:end_offset]` is the span.

Nothing here logs, stores or sends text, and errors never include text.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from importlib import resources
from typing import Literal

from pydantic import BaseModel, Field

ScreenLevel = Literal["none", "concern", "crisis"]
Subject = Literal["self", "other", "unknown"]

#: the package this module ports; reported on every result
SCREENER = "@meddevkit/crisis-signals"
MAX_SPAN_TEXT = 120
LEVEL_RANK: dict[str, int] = {"none": 0, "concern": 1, "crisis": 2}

CATEGORIES = frozenset({
    "suicidal_ideation_passive", "suicidal_ideation_active", "self_harm", "unsafe_with_self",
    "acute_distress", "immediacy", "history", "threatened_by_other",
})
DEFAULT_SCOPE = {
    "negated": "forward", "third_party": "forward", "hypothetical": "sentence", "past": "sentence",
    "resolved": "sentence-or-next", "idiom": "overlap", "quoted": "within",
}
DEFAULT_MAX_GAP = 50
_SET_SCOPES = frozenset({"forward", "sentence", "sentence-or-next", "within", "overlap"})
_BLOCK_SCOPES = frozenset({"clause", "sentence", "sentence-or-next", "between"})
_FRAGMENT_REF = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


# --------------------------------------------------------------------------- output


class Modifiers(BaseModel):
    negated: bool = False
    past: bool = False
    resolved: bool = False
    hypothetical: bool = False
    quoted: bool = False
    idiom: bool = False


class ScreenFinding(BaseModel):
    """One matched pattern, with its context and resulting level."""

    rule_id: str
    category: str
    base_level: ScreenLevel
    #: level after context modifiers
    level: ScreenLevel
    #: Python string indices into the screened text, end exclusive
    start_offset: int
    end_offset: int
    #: the matched span only, at most 120 characters
    text: str
    modifiers: Modifiers
    subject: Subject


class ScreenResult(BaseModel):
    """Result of screening one text. `none` does not mean the text is safe."""

    level: ScreenLevel = "none"
    #: a crisis finding co-occurs with a plan, means, timing or preparation cue
    immediacy: bool = False
    #: in text order, including findings context softened to `none`
    findings: list[ScreenFinding] = Field(default_factory=list)
    patterns_version: str = ""
    screener: str = SCREENER


# --------------------------------------------------------------------------- data


def _compile(rule_id: str, source: str, flags: str | None) -> re.Pattern[str]:
    f = flags or ""
    if f not in ("", "i"):
        raise ValueError(f"crisis-signals: {rule_id} uses unsupported flags; only \"i\" is allowed")
    try:
        return re.compile(source, re.IGNORECASE if f == "i" else 0)
    except re.error:
        raise ValueError(f"crisis-signals: {rule_id} does not compile") from None


def _expand(owner: str, source: str, fragments: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        body = fragments.get(m.group(1))
        if body is None:
            raise ValueError(f"crisis-signals: {owner} references an unknown fragment")
        return f"(?:{body})"
    return _FRAGMENT_REF.sub(sub, source)


@dataclass(eq=False)
class _Context:
    scope: str
    categories: frozenset[str]
    rules: frozenset[str]
    rx: re.Pattern[str] | None


@dataclass(eq=False)
class _Pattern:
    id: str
    category: str
    level: str
    rx: re.Pattern[str]
    order: int
    context: _Context | None = None


@dataclass(eq=False)
class _Cue:
    id: str
    rx: re.Pattern[str]
    modifier: str
    scope: str
    effect: str
    max_gap: int
    subject: str | None
    categories: tuple[str, ...] | None


@dataclass(eq=False)
class _Boundary:
    rx: re.Pattern[str]
    strong: bool


@dataclass
class CompiledData:
    version: str
    detection: list[_Pattern]
    gated: list[_Pattern]
    immediacy: list[_Pattern]
    cues: list[_Cue]
    boundaries: list[_Boundary]


def compile_data(file: dict) -> CompiledData:
    """Validate and compile a pattern file (the `PatternFile` shape)."""
    if not isinstance(file.get("version"), str) or not isinstance(file.get("patterns"), list) \
            or not isinstance(file.get("modifiers"), list):
        raise ValueError("crisis-signals: pattern file is malformed")
    fragments: dict[str, str] = {}
    for frag in file.get("fragments") or []:
        fid = frag.get("id")
        if not isinstance(fid, str) or not isinstance(frag.get("pattern"), str) or fid in fragments:
            raise ValueError(f"crisis-signals: fragment {fid} is malformed or duplicated")
        fragments[fid] = _expand(fid, frag["pattern"], fragments)

    def source(rule_id: str, pattern: str) -> str:
        return _expand(rule_id, pattern, fragments)

    ungated_ids = {p["id"] for p in file["patterns"] if p.get("context") is None}
    detection: list[_Pattern] = []
    gated: list[_Pattern] = []
    immediacy: list[_Pattern] = []
    for order, entry in enumerate(file["patterns"]):
        if entry.get("category") not in CATEGORIES or entry.get("level") not in LEVEL_RANK:
            raise ValueError(f"crisis-signals: {entry.get('id')} has an unknown category or level")
        p = _Pattern(entry["id"], entry["category"], entry["level"],
                     _compile(entry["id"], source(entry["id"], entry["pattern"]), entry.get("flags")), order)
        if entry.get("context") is not None:
            if p.category == "immediacy":
                raise ValueError(f"crisis-signals: {p.id} is an immediacy pattern and cannot be context-gated")
            p.context = _compile_context(entry, ungated_ids, source)
            gated.append(p)
        else:
            (immediacy if p.category == "immediacy" else detection).append(p)

    cues: list[_Cue] = []
    for entry in file["modifiers"]:
        modifier = entry.get("modifier")
        if modifier not in DEFAULT_SCOPE:
            raise ValueError(f"crisis-signals: {entry.get('id')} has an unknown modifier")
        effect = entry.get("effect") or "set"
        scope = entry.get("scope") or DEFAULT_SCOPE[modifier]
        if scope not in (_SET_SCOPES if effect == "set" else _BLOCK_SCOPES):
            raise ValueError(f"crisis-signals: {entry['id']} has a scope that does not fit its effect")
        cats = entry.get("categories")
        if cats is not None and not all(c in CATEGORIES for c in cats):
            raise ValueError(f"crisis-signals: {entry['id']} names an unknown category")
        cues.append(_Cue(
            id=entry["id"], rx=_compile(entry["id"], source(entry["id"], entry["pattern"]), entry.get("flags")),
            modifier=modifier, scope=scope, effect=effect,
            max_gap=entry.get("maxGap", DEFAULT_MAX_GAP), subject=entry.get("subject"),
            categories=None if cats is None else tuple(cats),
        ))

    boundaries = [
        _Boundary(_compile(b["id"], source(b["id"], b["pattern"]), b.get("flags")), b.get("strength") == "strong")
        for b in file.get("boundaries") or []
    ]
    return CompiledData(file["version"], detection, gated, immediacy, cues, boundaries)


def _compile_context(entry: dict, ungated_ids: set[str], source) -> _Context:
    ctx = entry["context"]
    rid = entry["id"]
    if not isinstance(ctx, dict) or ctx.get("scope") not in ("sentence", "adjacent"):
        raise ValueError(f"crisis-signals: {rid} has a malformed context")
    categories = ctx.get("categories") or []
    rules = ctx.get("rules") or []
    if not all(c in CATEGORIES and c != "immediacy" for c in categories):
        raise ValueError(f"crisis-signals: {rid} names an unknown context category")
    if not all(r in ungated_ids for r in rules):
        raise ValueError(f"crisis-signals: {rid} names an unknown or gated context rule")
    if not categories and not rules and ctx.get("pattern") is None:
        raise ValueError(f"crisis-signals: {rid} has an empty context")
    rx = None if ctx.get("pattern") is None else _compile(rid, source(rid, ctx["pattern"]), ctx.get("flags"))
    return _Context(ctx["scope"], frozenset(categories), frozenset(rules), rx)


# --------------------------------------------------------------------------- regex


def _find_all(rx: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    """Non-overlapping matches left to right, scanned like a JS global regex:
    an empty match is skipped and the scan moves on one character."""
    out: list[tuple[int, int]] = []
    pos, n = 0, len(text)
    while pos <= n:
        m = rx.search(text, pos)
        if m is None:
            break
        start, end = m.span()
        if end == start:
            pos = start + 1
            continue
        out.append((start, end))
        pos = end
    return out


def _find_cores(rx: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    """Like `_find_all`, but the span is the first participating capturing
    group when there is one. An empty group is a veto: no span."""
    out: list[tuple[int, int]] = []
    pos, n = 0, len(text)
    while pos <= n:
        m = rx.search(text, pos)
        if m is None:
            break
        start, end = m.span()
        if end == start:
            pos = start + 1
            continue
        pos = end
        core = next((m.span(g) for g in range(1, (rx.groups or 0) + 1) if m.span(g) != (-1, -1)), None)
        if core is None:
            out.append((start, end))
        elif core[1] > core[0]:
            out.append(core)
    return out


# --------------------------------------------------------------------------- text structure

_TERMINATORS = ".!?…"
_CLOSERS = "\"'”’)]"
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "approx", "dept", "appt", "mt",
})
_WS = re.compile(r"\s")
_ABBR_CHAR = re.compile(r"[A-Za-z.]")


def _is_ws(ch: str) -> bool:
    return _WS.match(ch) is not None


def _abbreviation_before(text: str, dot: int) -> bool:
    k = dot - 1
    while k >= 0 and _ABBR_CHAR.match(text[k]):
        k -= 1
    token = text[k + 1:dot].lower()
    return len(token) > 1 and token in _ABBREVIATIONS


def sentence_cuts(text: str) -> list[int]:
    """Sentence start positions after the first sentence, ascending."""
    raw: list[int] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == "\n":
            raw.append(i + 1)
            i += 1
            continue
        if ch in _TERMINATORS:
            j = i
            while j < n and text[j] in _TERMINATORS:
                j += 1
            run = j - i
            while j < n and text[j] in _CLOSERS:
                j += 1
            followed_by_break = j < n and _is_ws(text[j])
            if followed_by_break and not (ch == "." and run == 1 and _abbreviation_before(text, i)):
                raw.append(j)
            i = j
            continue
        i += 1
    cuts: list[int] = []
    last = p = 0
    seen = False
    for c in raw:
        if c <= last:
            continue
        while p < c:
            if not _is_ws(text[p]):
                seen = True
            p += 1
        if seen:
            cuts.append(c)
            last = c
            seen = False
    if cuts and not re.search(r"\S", text[cuts[-1]:]):
        cuts.pop()
    return cuts


class _TextIndex:
    def __init__(self, text: str, boundaries: list[_Boundary]):
        self._cuts = sentence_cuts(text)
        clause_ends: list[int] = []
        strong_ends: list[int] = []
        for b in boundaries:
            for _, end in _find_all(b.rx, text):
                clause_ends.append(end)
                if b.strong:
                    strong_ends.append(end)
        self._clause_ends = sorted(clause_ends)
        self._strong_ends = sorted(strong_ends)

    def sentence(self, pos: int) -> int:
        return bisect_right(self._cuts, pos)

    def clause(self, pos: int) -> int:
        return bisect_right(self._cuts, pos) + bisect_right(self._clause_ends, pos)

    def strong(self, pos: int) -> int:
        return bisect_right(self._cuts, pos) + bisect_right(self._strong_ends, pos)


# --------------------------------------------------------------------------- matching


@dataclass(eq=False)
class _Match:
    start: int
    end: int
    pattern: _Pattern


def _collect(text: str, patterns: list[_Pattern]) -> list[_Match]:
    return [_Match(s, e, p) for p in patterns for s, e in _find_cores(p.rx, text)]


def _dedupe(matches: list[_Match]) -> list[_Match]:
    """Drop overlaps: higher base level, then longer, then earlier, then file order wins."""
    by_priority = sorted(matches, key=lambda m: (
        -LEVEL_RANK[m.pattern.level], -(m.end - m.start), m.start, m.pattern.order))
    kept: list[_Match] = []
    starts: list[int] = []
    for m in by_priority:
        lo = bisect_left(starts, m.start)
        if lo > 0 and kept[lo - 1].end > m.start:
            continue
        if lo < len(kept) and kept[lo].start < m.end:
            continue
        kept.insert(lo, m)
        starts.insert(lo, m.start)
    return kept


# --------------------------------------------------------------------------- modifier scope

_MODIFIERS = ("negated", "past", "resolved", "hypothetical", "quoted", "idiom", "third_party")


@dataclass(eq=False)
class _Hit:
    start: int
    end: int
    cue: _Cue
    consumed: bool = False


@dataclass
class _PerModifier:
    forward: list[_Hit] = field(default_factory=list)
    forward_max_gap: int = 0
    between: list[_Hit] = field(default_factory=list)
    sentence: set[int] = field(default_factory=set)
    sentence_or_next: set[int] = field(default_factory=set)
    within: list[_Hit] = field(default_factory=list)
    overlap: list[_Hit] = field(default_factory=list)
    max_contain_len: int = 0
    block_clause: set[int] = field(default_factory=set)
    block_sentence: set[int] = field(default_factory=set)
    block_sentence_or_next: set[int] = field(default_factory=set)
    # sort keys, filled once the hits are sorted
    forward_ends: list[int] = field(default_factory=list)
    between_starts: list[int] = field(default_factory=list)
    within_starts: list[int] = field(default_factory=list)
    overlap_starts: list[int] = field(default_factory=list)


@dataclass
class _ModState:
    negated: bool
    past: bool
    resolved: bool
    hypothetical: bool
    quoted: bool
    idiom: bool
    third_party: bool
    subject_unknown: bool


def _has_in_range(s: set[int], lo: int, hi: int) -> bool:
    return bool(s) and any(i in s for i in range(lo, hi + 1))


def _overlaps_any(start: int, end: int, spans: list[_Match], span_starts: list[int]) -> bool:
    i = bisect_left(span_starts, end)
    return i > 0 and spans[i - 1].end > start


class _CueIndex:
    def __init__(self, text: str, cues: list[_Cue], index: _TextIndex, detection: list[_Match]):
        self._ix = index
        self._by: dict[str, _PerModifier] = {m: _PerModifier() for m in _MODIFIERS}
        det_starts = [d.start for d in detection]
        for cue in cues:
            buckets = [self._bucket(cue.modifier)] if cue.categories is None \
                else [self._bucket(cue.modifier, c) for c in cue.categories]
            spans = _find_all(cue.rx, text)
            for pm in buckets:
                self._add(pm, cue, spans, detection, det_starts)
        for pm in self._by.values():
            pm.forward.sort(key=lambda h: h.end)
            pm.between.sort(key=lambda h: h.start)
            pm.within.sort(key=lambda h: h.start)
            pm.overlap.sort(key=lambda h: h.start)
            pm.forward_ends = [h.end for h in pm.forward]
            pm.between_starts = [h.start for h in pm.between]
            pm.within_starts = [h.start for h in pm.within]
            pm.overlap_starts = [h.start for h in pm.overlap]

    def _bucket(self, m: str, category: str | None = None) -> _PerModifier:
        key = m if category is None else f"{m}|{category}"
        return self._by.setdefault(key, _PerModifier())

    def _add(self, pm, cue, spans, detection, det_starts) -> None:
        ix = self._ix
        for start, end in spans:
            hit = _Hit(start, end, cue)
            if cue.effect == "block":
                if cue.scope == "between":
                    pm.between.append(hit)
                elif cue.scope == "clause":
                    pm.block_clause.update(range(ix.clause(start), ix.clause(end) + 1))
                elif cue.scope == "sentence-or-next":
                    pm.block_sentence_or_next.add(ix.sentence(start))
                else:
                    pm.block_sentence.update(range(ix.strong(start), ix.strong(end) + 1))
                continue
            if cue.scope == "forward":
                hit.consumed = _overlaps_any(start, end, detection, det_starts)
                pm.forward.append(hit)
                pm.forward_max_gap = max(pm.forward_max_gap, cue.max_gap)
            elif cue.scope == "sentence":
                pm.sentence.update(range(ix.strong(start), ix.strong(end) + 1))
            elif cue.scope == "sentence-or-next":
                pm.sentence_or_next.add(ix.sentence(start))
            else:  # within / overlap
                (pm.within if cue.scope == "within" else pm.overlap).append(hit)
                pm.max_contain_len = max(pm.max_contain_len, end - start)

    def evaluate(self, start: int, end: int, category: str | None) -> _ModState:
        generic = [False]
        hypothetical = self._applies("hypothetical", start, end, category, generic)
        return _ModState(
            negated=self._applies("negated", start, end, category),
            past=self._applies("past", start, end, category),
            resolved=self._applies("resolved", start, end, category),
            hypothetical=hypothetical,
            quoted=self._applies("quoted", start, end, category),
            idiom=self._applies("idiom", start, end, category),
            third_party=self._applies("third_party", start, end, category),
            subject_unknown=hypothetical and generic[0],
        )

    def _applies(self, m, start, end, category, unknown: list[bool] | None = None) -> bool:
        buckets = [self._by[m]]
        if category is not None and f"{m}|{category}" in self._by:
            buckets.append(self._by[f"{m}|{category}"])
        if any(self._blocked(pm, start, end) for pm in buckets):
            return False
        applied = False
        for pm in buckets:
            if self._set_by(pm, start, end, unknown):
                applied = True
        return applied

    def _sentence_range(self, start: int, end: int) -> tuple[int, int]:
        return self._ix.sentence(start), self._ix.sentence(max(start, end - 1))

    def _blocked(self, pm: _PerModifier, start: int, end: int) -> bool:
        ix = self._ix
        if _has_in_range(pm.block_clause, ix.clause(start), ix.clause(end)):
            return True
        if _has_in_range(pm.block_sentence, ix.strong(start), ix.strong(end)):
            return True
        if pm.block_sentence_or_next:
            first, last = self._sentence_range(start, end)
            if _has_in_range(pm.block_sentence_or_next, first, last + 1):
                return True
        return False

    def _set_by(self, pm: _PerModifier, start: int, end: int, unknown: list[bool] | None) -> bool:
        ix = self._ix
        applied = _has_in_range(pm.sentence, ix.strong(start), ix.strong(end))
        if not applied and pm.sentence_or_next:
            first, last = self._sentence_range(start, end)
            applied = _has_in_range(pm.sentence_or_next, first, last + 1)
        if not applied and pm.within:
            applied = self._contains(pm.within, pm.within_starts, pm.max_contain_len, start, end,
                                     lambda h: h.start <= start and h.end >= end)
        if not applied and pm.overlap:
            applied = self._contains(pm.overlap, pm.overlap_starts, pm.max_contain_len, start, end,
                                     lambda h: h.start < end and h.end > start)
        # Forward cues last: they are the only ones that can carry a subject.
        if pm.forward:
            i = bisect_left(pm.forward_ends, start - pm.forward_max_gap)
            while i < len(pm.forward) and pm.forward[i].end <= start:
                h = pm.forward[i]
                i += 1
                if h.consumed or start - h.end > h.cue.max_gap:
                    continue
                if ix.clause(h.end) != ix.clause(start):
                    continue
                if self._blocked_between(pm, h.end, end):
                    continue
                if unknown is not None and h.cue.subject == "unknown":
                    unknown[0] = True
                applied = True
        return applied

    @staticmethod
    def _contains(hits, starts, max_len, start, end, test) -> bool:
        i = bisect_left(starts, start - max_len)
        while i < len(hits) and hits[i].start < end:
            if test(hits[i]):
                return True
            i += 1
        return False

    @staticmethod
    def _blocked_between(pm: _PerModifier, frm: int, to: int) -> bool:
        i = bisect_left(pm.between_starts, frm)
        while i < len(pm.between) and pm.between[i].start < to:
            if pm.between[i].end <= to:
                return True
            i += 1
        return False


# --------------------------------------------------------------------------- context gates


def _passing_gates(text, index, cues, suppress_idioms, detection, immediacy, gated_raw) -> list[_Match]:
    if not gated_raw:
        return []
    memo: dict[int, bool] = {}

    def qualifies(m: _Match) -> bool:
        ok = memo.get(id(m))
        if ok is None:
            mods = cues.evaluate(m.start, m.end, m.pattern.category)
            ok = not mods.negated and not (mods.idiom and suppress_idioms)
            memo[id(m)] = ok
        return ok

    per_pattern: dict[int, tuple[list[tuple[int, int]], list[int], int, dict[int, int]]] = {}
    out: list[_Match] = []
    for m in gated_raw:
        p = m.pattern
        ctx = per_pattern.get(id(p))
        if ctx is None:
            ctx = _context_spans(text, index, p, detection, immediacy, qualifies)
            per_pattern[id(p)] = ctx
        spans, span_starts, max_len, by_sentence = ctx
        first = index.sentence(m.start)
        last = index.sentence(max(m.start, m.end - 1))
        adjacent = p.context is not None and p.context.scope == "adjacent"
        lo, hi = (first - 1, last + 1) if adjacent else (first, last)
        count = sum(by_sentence.get(s, 0) for s in range(lo, hi + 1))
        # Context that overlaps the match itself does not count.
        i = bisect_left(span_starts, m.start - max_len)
        while i < len(spans):
            s_start, s_end = spans[i]
            i += 1
            if s_start >= m.end:
                break
            if s_end > m.start and lo <= index.sentence(s_start) <= hi:
                count -= 1
        if count > 0:
            out.append(m)
    return out


def _context_spans(text, index, pattern, detection, immediacy, qualifies):
    ctx = pattern.context
    spans: list[tuple[int, int]] = []
    if ctx is not None:
        for f in detection:
            if (f.pattern.category in ctx.categories or f.pattern.id in ctx.rules) and qualifies(f):
                spans.append((f.start, f.end))
        for f in immediacy:
            if f.pattern.id in ctx.rules and qualifies(f):
                spans.append((f.start, f.end))
        if ctx.rx is not None:
            spans.extend(_find_all(ctx.rx, text))
    spans.sort(key=lambda s: s[0])
    by_sentence: dict[int, int] = {}
    max_len = 0
    for s, e in spans:
        k = index.sentence(s)
        by_sentence[k] = by_sentence.get(k, 0) + 1
        max_len = max(max_len, e - s)
    return spans, [s for s, _ in spans], max_len, by_sentence


# --------------------------------------------------------------------------- level resolution

_RANK4 = ("quoted", "hypothetical", "negated", "past")


def _resolve(category: str, base: str, mods: _ModState, suppress_idioms: bool) -> tuple[str, str, Subject]:
    """(level, category, subject) for one detection finding; see the package's resolve.ts."""
    threat = category == "threatened_by_other"
    subject: Subject = "other" if threat or mods.third_party else "unknown" if mods.subject_unknown else "self"
    history = "history" if base == "crisis" else category

    if base == "none":
        return "none", category, subject
    if mods.idiom and suppress_idioms:
        return "none", category, subject
    if mods.third_party and not threat:
        return "none", category, subject
    if mods.past and mods.resolved:
        if category == "acute_distress":
            return "none", category, subject
        return "concern", history, subject

    outcomes: dict[str, str] = {}
    if mods.quoted:
        outcomes["quoted"] = "concern"
    if mods.hypothetical:
        outcomes["hypothetical"] = "concern"
    if mods.negated:
        outcomes["negated"] = "none" if category == "acute_distress" else "concern"
    if mods.past:
        outcomes["past"] = "concern"
    decider = None
    for m in _RANK4:
        if m in outcomes and (decider is None or LEVEL_RANK[outcomes[m]] > LEVEL_RANK[outcomes[decider]]):
            decider = m
    if decider is None:
        return base, category, subject
    level = outcomes[decider] if LEVEL_RANK[outcomes[decider]] <= LEVEL_RANK[base] else base
    return level, history if decider == "past" else category, subject


# --------------------------------------------------------------------------- screen


def _immediacy_active(mods: _ModState, suppress_idioms: bool) -> bool:
    return not (mods.negated or mods.past or mods.hypothetical or mods.quoted or mods.third_party
                or (mods.idiom and suppress_idioms))


def _finding(text: str, m: _Match, category: str, level: str, mods: _ModState, subject: Subject) -> ScreenFinding:
    return ScreenFinding(
        rule_id=m.pattern.id, category=category, base_level=m.pattern.level, level=level,
        start_offset=m.start, end_offset=m.end, text=text[m.start:min(m.end, m.start + MAX_SPAN_TEXT)],
        modifiers=Modifiers(negated=mods.negated, past=mods.past, resolved=mods.resolved,
                            hypothetical=mods.hypothetical, quoted=mods.quoted, idiom=mods.idiom),
        subject=subject,
    )


def screen_with(data: CompiledData, text: str, *, suppress_idioms: bool = True) -> ScreenResult:
    """Screen `text` with a compiled pattern file; `screen_text` uses the vendored one."""
    if not isinstance(text, str):
        raise TypeError("crisis-signals: screen_text expects a string")
    if not text:
        return ScreenResult(patterns_version=data.version)

    index = _TextIndex(text, data.boundaries)
    ungated_raw = _collect(text, data.detection)
    detection = _dedupe(ungated_raw)
    immediacy = _dedupe(_collect(text, data.immediacy))
    cues = _CueIndex(text, data.cues, index, detection)

    passing = _passing_gates(text, index, cues, suppress_idioms, detection, immediacy,
                             _collect(text, data.gated))
    if passing:
        detection = _dedupe(ungated_raw + passing)
        cues = _CueIndex(text, data.cues, index, detection)

    findings: list[ScreenFinding] = []
    level = "none"
    crisis_present = False
    for m in detection:
        mods = cues.evaluate(m.start, m.end, m.pattern.category)
        r_level, r_category, r_subject = _resolve(m.pattern.category, m.pattern.level, mods, suppress_idioms)
        if r_level == "crisis":
            crisis_present = True
        if LEVEL_RANK[r_level] > LEVEL_RANK[level]:
            level = r_level
        findings.append(_finding(text, m, r_category, r_level, mods, r_subject))

    immediacy_flag = False
    for m in immediacy:
        mods = cues.evaluate(m.start, m.end, "immediacy")
        active = crisis_present and _immediacy_active(mods, suppress_idioms)
        immediacy_flag = immediacy_flag or active
        subject: Subject = "other" if mods.third_party else "unknown" if mods.subject_unknown else "self"
        findings.append(_finding(text, m, "immediacy", "crisis" if active else "none", mods, subject))

    findings.sort(key=lambda f: (f.start_offset, f.end_offset))
    return ScreenResult(level=level, immediacy=immediacy_flag, findings=findings, patterns_version=data.version)


def _load() -> CompiledData:
    raw = resources.files(__package__).joinpath("data/crisis.patterns.json").read_text(encoding="utf-8")
    return compile_data(json.loads(raw))


#: the vendored, compiled pattern file
DATA: CompiledData = _load()
PATTERNS_VERSION: str = DATA.version


def screen_text(text: str, *, suppress_idioms: bool = True) -> ScreenResult:
    """Screen one text for first-person crisis language.

    Returns the highest level among the findings (`none`, `concern`, `crisis`),
    an `immediacy` flag and every finding, including those context softened to
    `none`. A `none` result does not mean the text is safe.
    """
    return screen_with(DATA, text, suppress_idioms=suppress_idioms)
