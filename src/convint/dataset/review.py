"""Export items for human judgement as an editable file, and read them back.

A markdown file rather than an interactive prompt: judgement on a conversation
turn needs the surrounding context visible, wants thinking time, and benefits
from being reviewable in a diff. One line per item is edited; everything else is
context.
"""

from __future__ import annotations

import json
import re

from ..domain.enums import Action
from .adjudicate import HUMAN, append_human, load_human, queue
from .build import OUT

REVIEW = OUT / "REVIEW.md"

_VALID = [a.value for a in Action]
_LINE = re.compile(r"^DECISION\s*\[(?P<id>[^\]]+)\]\s*:\s*(?P<value>\S+)", re.M)
_NOTE = re.compile(r"^NOTE\s*\[(?P<id>[^\]]+)\]\s*:\s*(?P<value>.*)$", re.M)

HEADER = """\
# Human judgement queue

Edit the `DECISION[...]` line under each item, then run:

    make label-import

Valid values: `follow_up`, `advance`, `synthesize`, `refuse_and_continue`.

Leave a line unchanged to accept the proposal. Add an optional `NOTE[...]` line
if the reasoning is worth keeping — those are the ones that improve the rule
rather than just the labels.

**The question to answer for each item:** given only what the person has said so
far and how many follow-ups have already been spent on this thread, should the
interviewer ask *another question about this same thread*, *move on*, or *close
and synthesize*?

These items were chosen because the written rule and the running implementation
disagree, so your answer settles something. Items where they already agree are
not included.

---
"""


def export(split: str = "corpus", limit: int | None = None) -> tuple[object, int]:
    rows = queue(split, disagreements_only=True)
    if limit:
        rows = rows[:limit]

    parts = [HEADER]
    for n, (item, label, disagreement) in enumerate(rows, 1):
        context = "\n".join(f"> {t}" for t in item.user_turns[:-1]) or "> (start of thread)"
        parts.append(f"""
## {n}. `{item.item_id}`

**Earlier in this thread**

{context}

**The turn to judge**

> {item.text}

**State the interviewer can see**

| | |
|---|---|
| sufficiency | `{item.specificity.value}` specificity / `{item.ownership.value}` ownership |
| follow-ups spent on this thread | {item.followups_used} (floor {item.floor}, ceiling {item.ceiling}) |
| detected signal | `{item.signal.value}` |

The written rule proposes **`{label.action.value}`** — {label.rationale}
The running implementation says **`{disagreement}`**.

```
DECISION[{item.item_id}]: {label.action.value}
NOTE[{item.item_id}]:
```

---
""")
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    REVIEW.write_text("".join(parts), encoding="utf-8")
    return REVIEW, len(rows)


def import_decisions(split: str = "corpus") -> dict[str, int]:
    if not REVIEW.exists():
        raise FileNotFoundError(f"{REVIEW} does not exist — run `make label` first.")

    text = REVIEW.read_text(encoding="utf-8")
    notes = {m.group("id"): m.group("value").strip() for m in _NOTE.finditer(text)}
    already = load_human()

    recorded = skipped = invalid = 0
    for match in _LINE.finditer(text):
        item_id, value = match.group("id"), match.group("value").strip().strip("`")
        if value not in _VALID:
            invalid += 1
            continue
        if item_id in already:
            skipped += 1
            continue
        append_human({
            "item_id": item_id, "action": value, "split": split,
            "source": "human", "note": notes.get(item_id, ""),
        })
        recorded += 1

    return {"recorded": recorded, "already_present": skipped, "invalid": invalid,
            "total_human_labels": len(load_human()) }
