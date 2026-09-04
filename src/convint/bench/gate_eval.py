"""Evaluate the gate against the turn-decision labels.

The headline is `premature_advance_rate` - moving on when the material was not
there - because that is the failure this component exists to prevent. It is
ALWAYS reported next to `stall_rate`, its mirror: a policy that always follows
up scores a perfect zero on the headline alone, so the headline alone is
gameable and meaningless.

The dumb baselines are not decoration. If the gate cannot beat
`always_follow_up` on this corpus, the two-axis ladder is not earning its
complexity.
"""

from __future__ import annotations

from ..domain.enums import Action, Specificity
from ..domain.gate import decide
from ..domain.plan import Budget, InterviewPlan, StageSpec, TopicSpec
from ..domain.state import ConversationState, TopicRecord, Turn
from ..dataset.build import load
from ..dataset.schema import Item, Label
from ..dataset.synth import minimal_pairs


def _plan(item: Item) -> InterviewPlan:
    return InterviewPlan(
        plan_id="eval",
        stages=[StageSpec(stage_id="s", completion_signal="stage_complete")],
        topics=[TopicSpec(topic_id="t", stage="s",
                          budget=Budget(floor=item.floor, ceiling=item.ceiling))],
    )


def _state(item: Item) -> ConversationState:
    return ConversationState(
        turns=[Turn(role="user", content=item.text)],
        topics=[TopicRecord(
            topic_id="t", stage="s", followups_used=item.followups_used,
            specificity=item.specificity, ownership=item.ownership,
        )],
        current_topic_id="t",
        signal=item.signal,
        coverage={"s": item.stage_covered},
    )


# --- policies --------------------------------------------------------------

def gate_policy(item: Item) -> Action:
    return decide(_state(item), _plan(item)).action


def always_follow_up(item: Item) -> Action:
    return Action.FOLLOW_UP


def always_advance(item: Item) -> Action:
    return Action.ADVANCE


def budget_only(item: Item) -> Action:
    """Ignores content entirely: follow up until the ceiling, then move on.
    This is the turn-counter behaviour the component was built to replace."""
    return Action.FOLLOW_UP if item.followups_used < item.ceiling else Action.ADVANCE


def length_threshold(item: Item) -> Action:
    """Advance if they wrote a lot. The cheapest possible content signal."""
    return Action.ADVANCE if len(item.text.split()) >= 40 else Action.FOLLOW_UP


POLICIES = {
    "gate": gate_policy,
    "always_follow_up": always_follow_up,
    "always_advance": always_advance,
    "budget_only": budget_only,
    "length_threshold": length_threshold,
}


# --- metrics ---------------------------------------------------------------

def evaluate_policy(policy, items: list[Item], labels: dict[str, Label],
                    pairs: list[tuple[str, str]] | None = None) -> dict:
    correct = strict = 0
    prem_n = prem_hit = stall_n = stall_hit = 0

    for item in items:
        label = labels[item.item_id]
        predicted = policy(item)

        strict += predicted is label.action
        correct += label.is_correct(predicted)

        # must-follow-up items: advancing here is the failure under study
        if label.action is Action.FOLLOW_UP and Action.ADVANCE not in label.acceptable:
            prem_n += 1
            prem_hit += predicted in (Action.ADVANCE, Action.SYNTHESIZE)

        # must-advance items: refusing to move on is the mirror failure
        if label.action is Action.ADVANCE and Action.FOLLOW_UP not in label.acceptable:
            stall_n += 1
            stall_hit += predicted is Action.FOLLOW_UP

    pair_total = pair_ok = 0
    if pairs:
        predictions = {i.item_id: policy(i) for i in items}
        for a, b in pairs:
            if a in predictions and b in predictions:
                pair_total += 1
                pair_ok += (
                    labels[a].is_correct(predictions[a])
                    and labels[b].is_correct(predictions[b])
                )

    n = len(items)
    return {
        "n": n,
        "minimal_pair_accuracy": (pair_ok / pair_total) if pair_total else None,
        "minimal_pair_n": pair_total,
        "accuracy_strict": strict / n,
        "accuracy_acceptable": correct / n,
        "premature_advance_rate": (prem_hit / prem_n) if prem_n else None,
        "premature_advance_n": prem_n,
        "stall_rate": (stall_hit / stall_n) if stall_n else None,
        "stall_n": stall_n,
    }


def load_human_labels() -> dict[str, Action]:
    import json
    import pathlib

    from ..dataset.adjudicate import HUMAN

    if not HUMAN.exists():
        return {}
    return {
        (r := json.loads(line))["item_id"]: Action(r["action"])
        for line in pathlib.Path(HUMAN).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def run(split: str = "synth") -> dict:
    """Evaluate on one split. `synth` is balanced and carries minimal pairs;
    `corpus` is realistic but skewed and weakly labelled."""
    from ..dataset.build import build
    from ..dataset.synth import build_from_banks

    items, label_list = build_from_banks() if split == "synth" else build()
    labels = {l.item_id: l for l in label_list}

    if split == "human":
        # Only adjudicated items, scored against the human's call.
        human = load_human_labels()
        if not human:
            raise RuntimeError("no human labels yet — run `make label` first")
        items = [i for i in items if i.item_id in human]
        labels = {
            iid: Label(item_id=iid, action=action, source="human", confidence="high")
            for iid, action in human.items()
        }
    pairs = minimal_pairs(items, label_list) if split == "synth" else []
    return {
        name: evaluate_policy(fn, items, labels, pairs)
        for name, fn in POLICIES.items()
    }


PROVENANCE = {
    "synth": (
        "labels are SPEC-derived (from the written rule, not human judgement).\n"
        "  This measures CONFORMANCE and COVERAGE, not whether the rule is right.\n"
        "  The gate scoring 100% here is expected and proves nothing about validity;\n"
        "  the informative numbers are the BASELINES - note budget_only at 88%\n"
        "  accuracy but 0% on minimal pairs, i.e. accurate-looking while blind to\n"
        "  sufficiency."
    ),
    "corpus": (
        "labels are WEAK (inferred from each transcript's own next user turn).\n"
        "  Realistic but skewed: every golden punishes premature advance and none\n"
        "  punishes stalling, so always_follow_up looks strong. Directional only."
    ),
    "human": "labels are HUMAN-ADJUDICATED. These are the only validity evidence.",
}


def format_report(result: dict, split: str = "synth") -> str:
    lines = [
        f"gate evaluation — split: {split}",
        f"  {PROVENANCE.get(split, '')}",
        "",
    ]
    lines += [
        f"  {'policy':<20} {'acc':>6} {'premature↓':>11} {'stall↓':>8} {'pairs':>7}",
    ]
    for name, m in result.items():
        prem = f"{m['premature_advance_rate']:.0%}" if m["premature_advance_rate"] is not None else "  n/a"
        stall = f"{m['stall_rate']:.0%}" if m["stall_rate"] is not None else "  n/a"
        pair = f"{m['minimal_pair_accuracy']:.0%}" if m["minimal_pair_accuracy"] is not None else "  n/a"
        lines.append(
            f"  {name:<20} {m['accuracy_strict']:>6.0%}"
            f" {prem:>11} {stall:>8} {pair:>7}"
        )
    first = next(iter(result.values()))
    lines += ["", f"  premature-advance denominator: {first['premature_advance_n']} items"
                  f"   stall denominator: {first['stall_n']} items"]
    return "\n".join(lines)
