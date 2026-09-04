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


def _wrap(text: str, width: int = 76, indent: str = "    ") -> str:
    import textwrap

    return "\n".join(textwrap.fill(text, width, initial_indent=indent,
                                    subsequent_indent=indent) for _ in [0])


def run_session(split: str, limit: int, disagreements_only: bool) -> int:  # pragma: no cover
    rows = queue(split, disagreements_only)
    if not rows:
        print("Nothing to adjudicate — every item already has a human label.")
        return 0

    total = len(rows)
    shown = rows[:limit]
    print()
    print("=" * 78)
    print("  HUMAN JUDGEMENT")
    print("=" * 78)
    print(f"  {total} item(s) queued in '{split}'; showing {len(shown)}.")
    print()
    print("  For each one: given only what the person has said so far, and how many")
    print("  follow-ups have already been spent on this thread — should the interviewer")
    print("  ask another question about THIS thread, move on, or close and synthesize?")
    print()
    print("  [f] follow_up   [a] advance   [s] synthesize   [r] refuse")
    print("  [enter] accept the proposal    [?] why this item    [q] save and quit")
    print("=" * 78)

    count = 0
    for n, (item, label, disagreement) in enumerate(shown, 1):
        print()
        print(f"┌─ {n}/{len(shown)}  {item.item_id}")
        print("│")
        for turn in item.user_turns[:-1][-3:]:
            print(_wrap(turn[:400], indent="│  · "))
        print("│")
        print("│  THE TURN TO JUDGE:")
        print(_wrap(item.text[:700], indent="│    "))
        print("│")
        print(f"│  state: {item.specificity.value}/{item.ownership.value}   "
              f"follow-ups spent: {item.followups_used} "
              f"(floor {item.floor}, ceiling {item.ceiling})   "
              f"signal: {item.signal.value}")
        print(f"│  rule proposes: {label.action.value}")
        if disagreement:
            print(f"│  implementation says: {disagreement}   <- they disagree, so your call settles it")
        print("└" + "─" * 60)

        chosen = None
        while chosen is None:
            try:
                answer = input(f"  [{label.action.value}] > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "q"
            if answer == "q":
                print(f"\nSaved {count} adjudication(s) -> {HUMAN}")
                return 0
            if answer == "?":
                print(f"  rationale: {label.rationale}")
                continue
            if answer == "":
                chosen = label.action.value
            elif answer in CHOICES:
                chosen = CHOICES[answer]
            else:
                print(f"  not a choice. use f/a/s/r, enter, ? or q")
                continue

        note = ""
        try:
            note = input("  note (optional, enter to skip) > ").strip()
        except (EOFError, KeyboardInterrupt):
            pass

        append_human({
            "item_id": item.item_id, "action": chosen,
            "agreed_with_spec": chosen == label.action.value,
            "split": split, "source": "human", "note": note,
        })
        count += 1
        print(f"  recorded: {chosen}")

    print()
    print(f"Done. Recorded {count} adjudication(s) -> {HUMAN}")
    remaining = total - count
    if remaining:
        print(f"{remaining} still queued — run `make label` again to continue.")
    return 0
