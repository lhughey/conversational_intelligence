"""Label the held-out sufficiency set - the user's labels are its only gold.

What the labeller sees is the interviewer's question and the person's answer,
nothing else: no persona, no topic, and never the author's rung (this module
does not read that file; a test pins it), so nothing anchors the judgement.
Items come in a seeded shuffle so persona and rung order cannot cue answers.

Two ways in, same labels file:
  * `run_session` - interactive; every label is appended the moment it is
    given, so quitting loses nothing and the next session resumes at the
    first unlabelled item;
  * `export` / `import_sheet` - an editable markdown sheet with blank
    `S[...]` / `O[...]` lines (no pre-filled proposal to accept).
"""

from __future__ import annotations

import pathlib
import re
import textwrap
from collections.abc import Callable

from ..bench import heldout
from ..domain.enums import Ownership, Specificity

SHEET_NAME = "label-sheet.md"

RUBRIC = """\
Judge the ANSWER only. The question is context: what the interviewer said is
not the person's material. Judge each answer on its own, as if nothing came
before it.

SPECIFICITY - how concrete is the material in the answer?
  S0  Nothing usable: a deflection ("not sure"), a one-word answer, a comment
      about the interview itself, or a pure confirmation / closing ("yes, that
      fits", "no, that's everything"). Length does not matter: a long sign-off
      is still S0.
  S1  A generalization about themselves or their world, with no concrete
      instance behind it ("I'm good with people", "I work in logistics").
  S2  Concrete: a recurring practice, a named setting, or a habit described
      with real detail - but no single bounded event. Also S2: one event that
      is missing any of scene, stakes, action, outcome.
  S3  An episode: ONE bounded event with all four - scene (when / where),
      stakes (what mattered, what could go wrong), action (what they did),
      outcome (what came of it). If any one is missing, it is S2.

OWNERSHIP - who did the meaning-making? Ignore how vivid the answer is.
  O0  Reports what happened or what they do, and draws no conclusion about
      themselves. The default for stories, however rich.
  O1  Puts an existing label on themselves ("I'm a fixer", "I'm careful"), or
      accepts a framing someone offered ("yeah, that fits").
  O2  Says something new about their own pattern, in their own words, derived
      from their own material - a realization, not a self-description.
      Test: strike every sentence that describes what happened; if no claim
      about themselves survives, it is O0 or O1.

The axes are independent: judge each separately.
"""

REMINDER = ("S0 nothing usable | S1 generalization | S2 concrete, no single event | "
            "S3 one event: scene+stakes+action+outcome\n"
            "O0 reports only | O1 existing label / accepts a frame | O2 new self-derivation")

_S = re.compile(r"^\s*s?\s*([0-3])\s*$", re.I)
_O = re.compile(r"^\s*o?\s*([0-2])\s*$", re.I)
_BOTH = re.compile(r"^\s*s?\s*([0-3])\s*[/,\s]?\s*o?\s*([0-2])\s*$", re.I)


def parse_specificity(text: str) -> Specificity | None:
    m = _S.match(text or "")
    return Specificity(f"S{m.group(1)}") if m else None


def parse_ownership(text: str) -> Ownership | None:
    m = _O.match(text or "")
    return Ownership(f"O{m.group(1)}") if m else None


def parse_both(text: str) -> tuple[Specificity, Ownership] | None:
    """`2 1`, `2/1`, `21`, `S2 O1`, `s2o1` -> (S2, O1)."""
    m = _BOTH.match(text or "")
    return (Specificity(f"S{m.group(1)}"), Ownership(f"O{m.group(2)}")) if m else None


def _wrap(text: str, indent: str, width: int = 78) -> str:
    return textwrap.fill(text, width, initial_indent=indent,
                         subsequent_indent=" " * len(indent))


# -- interactive -------------------------------------------------------------

def run_session(limit: int | None = None, *, ask: Callable[[str], str] = input,
                say: Callable[[str], None] = print,
                items_path: pathlib.Path | None = None,
                labels_path: pathlib.Path | None = None) -> int:
    """Label unlabelled items, most recent session's place first. `limit` of
    None or 0 means every remaining item. Returns 0."""
    raw_ask = ask

    def ask(prompt: str) -> str:  # Ctrl-D / Ctrl-C save and quit, like `q`
        try:
            return raw_ask(prompt)
        except (EOFError, KeyboardInterrupt):
            return "q"

    items = heldout.load_items(items_path)
    labels = heldout.load_labels(labels_path, items=items)
    todo = heldout.queue(items, labels)
    total, done_before = len(items), len(labels)
    if not todo:
        say(f"Nothing to label - all {total} held-out items have your label.")
        return 0
    shown = todo[:limit] if limit else todo

    rule = "=" * 78
    say("")
    say(rule)
    say("  HELD-OUT LABELLING - your labels are the only gold this set has")
    say(rule)
    say(f"  {done_before} of {total} labelled so far; {len(todo)} to go"
        + (f" (showing {len(shown)} this session)." if len(shown) < len(todo) else "."))
    say("  This set is never used for tuning. Label what you read, not what you")
    say("  think an assessor would say.")
    say("")
    say(textwrap.indent(RUBRIC, "  "))
    say("  Keys: a digit per axis, or both at once (\"2 1\" = S2/O1)."
        "  ? rubric   - skip   q save and quit")
    say(rule)

    count = 0
    for n, item in enumerate(shown, 1):
        say("")
        say("-" * 78)
        say(f" {n} of {len(shown)}   {item.id}"
            f"   ({done_before + count} of {total} labelled)")
        say("")
        say(_wrap(item.question, " QUESTION  "))
        say("")
        say(_wrap(item.text, " ANSWER    "))
        say("")
        say(textwrap.indent(REMINDER, " "))
        say("-" * 78)

        spec: Specificity | None = None
        own: Ownership | None = None
        skipped = False
        while spec is None:
            answer = ask("  specificity 0-3 > ").strip().lower()
            if answer == "q":
                return _finish(say, count, items, labels_path)
            if answer == "?":
                say(textwrap.indent(RUBRIC, "  "))
                continue
            if answer == "-":
                skipped = True
                break
            both = parse_both(answer)
            if both:
                spec, own = both
                break
            spec = parse_specificity(answer)
            if spec is None:
                say("  not a choice: 0-3 (or \"2 1\" for both), ?, -, q")
        if skipped:
            say("  skipped - it stays in the queue for next time")
            continue
        while own is None:
            answer = ask("  ownership 0-2 > ").strip().lower()
            if answer == "q":
                return _finish(say, count, items, labels_path)
            if answer == "?":
                say(textwrap.indent(RUBRIC, "  "))
                continue
            own = parse_ownership(answer)
            if own is None:
                say("  not a choice: 0-2, ?, q")

        note = ask("  note (optional, enter to skip) > ").strip()
        stop = note == "q"  # quit at the note prompt keeps the label just given
        heldout.append_label(heldout.make_label(item, spec, own, note="" if stop else note,
                                                via="interactive"), labels_path)
        count += 1
        say(f"  recorded {spec.value}/{own.value}")
        if stop:
            return _finish(say, count, items, labels_path)

    return _finish(say, count, items, labels_path)


def _finish(say: Callable[[str], None], count: int, items: list,
            labels_path: pathlib.Path | None) -> int:
    path = labels_path or heldout.LABELS
    say("")
    say(f"Saved {count} label(s) this session -> {path}")
    # Totals only: a per-persona breakdown would tell the labeller which
    # persona the items they just saw came from.
    st = heldout.status(items, heldout.load_labels(labels_path, items=items))
    say(f"{st['n_labelled']} of {st['n_items']} held-out items labelled "
        f"(scoring needs >= {st['min_labelled']}).")
    if st["n_labelled"] < st["n_items"]:
        say("Run `make label-heldout` again to continue where you left off.")
    return 0


# -- sheet -------------------------------------------------------------------

_SLINE = re.compile(r"^S\[(?P<id>[^\]]+)\]:[ \t]*(?P<value>[^\n]*)$", re.M)
_OLINE = re.compile(r"^O\[(?P<id>[^\]]+)\]:[ \t]*(?P<value>[^\n]*)$", re.M)
_NLINE = re.compile(r"^NOTE\[(?P<id>[^\]]+)\]:[ \t]*(?P<value>[^\n]*)$", re.M)

SHEET_HEADER = """\
# Held-out labelling sheet

Fill in the `S[...]` and `O[...]` lines under each item, then run:

    make label-heldout-import

`S` takes `S0`-`S3` (or `0`-`3`); `O` takes `O0`-`O2` (or `0`-`2`). Leave both
blank to skip an item - it stays unlabelled and appears in the next export.
`NOTE[...]` is optional. Items are in a fixed shuffled order; there is no
proposal to accept, on purpose. Re-importing is safe: items that already have
a label are skipped.

This set is never used for tuning. Label what you read.

## Rubric

```
{rubric}```

---
"""


def sheet_path() -> pathlib.Path:
    return heldout.DIR / SHEET_NAME


def export(path: pathlib.Path | None = None, *,
           items_path: pathlib.Path | None = None,
           labels_path: pathlib.Path | None = None) -> tuple[pathlib.Path, int]:
    """Write every unlabelled item, in presentation order, to an editable sheet."""
    path = path or sheet_path()
    items = heldout.load_items(items_path)
    todo = heldout.queue(items, heldout.load_labels(labels_path, items=items))
    parts = [SHEET_HEADER.format(rubric=RUBRIC)]
    for n, item in enumerate(todo, 1):
        answer = "\n".join(f"> {line}" for line in item.text.splitlines())
        parts.append(f"""
## {n}. `{item.id}`

**Question:** {item.question}

{answer}

```
S[{item.id}]:
O[{item.id}]:
NOTE[{item.id}]:
```

---
""")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")
    return path, len(todo)


def import_sheet(path: pathlib.Path | None = None, *,
                 items_path: pathlib.Path | None = None,
                 labels_path: pathlib.Path | None = None) -> dict:
    """Append every fully filled-in item from the sheet to the labels file."""
    path = path or sheet_path()
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist - run `make label-heldout-export` first.")
    text = path.read_text(encoding="utf-8")
    items = {i.id: i for i in heldout.load_items(items_path)}
    already = heldout.load_labels(labels_path, items=list(items.values()))
    s_vals = {m.group("id"): m.group("value").strip().strip("`") for m in _SLINE.finditer(text)}
    o_vals = {m.group("id"): m.group("value").strip().strip("`") for m in _OLINE.finditer(text)}
    notes = {m.group("id"): m.group("value").strip() for m in _NLINE.finditer(text)}

    counts = {"recorded": 0, "already_labelled": 0, "blank": 0, "incomplete": 0, "invalid": 0}
    problems: list[str] = []
    for item_id in s_vals.keys() | o_vals.keys():
        s_raw, o_raw = s_vals.get(item_id, ""), o_vals.get(item_id, "")
        if not s_raw and not o_raw:
            counts["blank"] += 1
            continue
        if item_id not in items:
            counts["invalid"] += 1
            problems.append(f"{item_id}: not a held-out item id")
            continue
        if item_id in already:
            counts["already_labelled"] += 1
            continue
        if not s_raw or not o_raw:
            counts["incomplete"] += 1
            problems.append(f"{item_id}: needs both S and O")
            continue
        spec, own = parse_specificity(s_raw), parse_ownership(o_raw)
        if spec is None or own is None:
            counts["invalid"] += 1
            problems.append(f"{item_id}: S={s_raw!r} O={o_raw!r}")
            continue
        heldout.append_label(heldout.make_label(items[item_id], spec, own,
                                                note=notes.get(item_id, ""), via="sheet"),
                             labels_path)
        counts["recorded"] += 1

    st = heldout.status(list(items.values()),
                        heldout.load_labels(labels_path, items=list(items.values())))
    return {**counts, "problems": sorted(problems),
            "labelled": st["n_labelled"], "of": st["n_items"]}
