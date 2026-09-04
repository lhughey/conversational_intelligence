"""Human adjudication - the only thing that turns labels into validity evidence.

Spec labels prove conformance. Weak labels prove nothing on their own. A human
saying "given this state, the interviewer should have done X" is the only
independent signal, so this exists to make producing that signal cheap.

Two economies:
  * Items are ordered by INFORMATION, not by file order - disagreements between
    the spec label and the live gate come first, because those are where a
    human's opinion actually changes something.
  * Adjudications are appended to their own file and never overwrite generated
    labels, so the generated set can be rebuilt without losing human work.
"""

from __future__ import annotations

import json
import pathlib

from ..bench.gate_eval import gate_policy
from .build import OUT
from .schema import Item, Label

HUMAN = OUT / "human_labels.jsonl"
CHOICES = {"f": "follow_up", "a": "advance", "s": "synthesize", "r": "refuse_and_continue"}


def load_human() -> dict[str, dict]:
    if not HUMAN.exists():
        return {}
    rows = [json.loads(l) for l in HUMAN.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {r["item_id"]: r for r in rows}


def append_human(record: dict) -> None:
    HUMAN.parent.mkdir(parents=True, exist_ok=True)
    with HUMAN.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_split(split: str) -> tuple[list[Item], list[Label]]:
    from .build import build
    from .synth import build_from_banks

    return build_from_banks() if split == "synth" else build()


def queue(split: str, disagreements_only: bool = False) -> list[tuple[Item, Label, str]]:
    """Items worth a human's attention, most informative first."""
    items, labels = _load_split(split)
    by_id = {l.item_id: l for l in labels}
    done = load_human()

    rows = []
    for item in items:
        if item.item_id in done:
            continue
        label = by_id[item.item_id]
        predicted = gate_policy(item)
        disagrees = not label.is_correct(predicted)
        if disagreements_only and not disagrees:
            continue
        rows.append((item, label, predicted.value if disagrees else ""))

    # disagreements first: those are where an opinion changes something
    rows.sort(key=lambda r: (r[2] == "", r[0].item_id))
    return rows


def run_session(split: str, limit: int, disagreements_only: bool) -> int:  # pragma: no cover
    rows = queue(split, disagreements_only)
    if not rows:
        print("nothing to adjudicate — every item already has a human label.")
        return 0

    print(f"{len(rows)} unlabelled items in '{split}'. Showing up to {limit}.")
    print("keys: [f]ollow_up  [a]dvance  [s]ynthesize  [r]efuse  [enter]=accept  [q]uit\n")

    count = 0
    for item, label, disagreement in rows[:limit]:
        print("─" * 72)
        print(f"{item.item_id}")
        print(f"  state: {item.specificity.value}/{item.ownership.value}  "
              f"follow-ups {item.followups_used} of {item.floor}-{item.ceiling}  "
              f"signal={item.signal.value}")
        for turn in item.user_turns[:-1]:
            print(f"  · {turn[:100]}")
        print(f"  USER: {item.text[:300]}")
        print(f"  proposed: {label.action.value}  ({label.rationale})")
        if disagreement:
            print(f"  ** the live gate says {disagreement} — they disagree **")

        try:
            answer = input("  your call> ").strip().lower()
        except EOFError:
            break
        if answer == "q":
            break

        chosen = CHOICES.get(answer, label.action.value)
        append_human({
            "item_id": item.item_id, "action": chosen,
            "agreed_with_spec": chosen == label.action.value,
            "split": split, "source": "human",
        })
        count += 1

    print(f"\nrecorded {count} adjudications -> {HUMAN}")
    return 0
