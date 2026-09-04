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

def evaluate_policy(policy, items: list[Item], labels: dict[str, Label]) -> dict:
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

    n = len(items)
    return {
        "n": n,
        "accuracy_strict": strict / n,
        "accuracy_acceptable": correct / n,
        "premature_advance_rate": (prem_hit / prem_n) if prem_n else None,
        "premature_advance_n": prem_n,
        "stall_rate": (stall_hit / stall_n) if stall_n else None,
        "stall_n": stall_n,
    }


def run() -> dict:
    items, label_list = load()
    labels = {l.item_id: l for l in label_list}
    return {name: evaluate_policy(fn, items, labels) for name, fn in POLICIES.items()}


def format_report(result: dict) -> str:
    lines = [
        "gate evaluation  (labels are WEAK - derived from each transcript's own",
        "next turn, not independent human judgement. Directional only.)",
        "",
        f"  {'policy':<20} {'acc':>6} {'acc±':>6} {'premature↓':>11} {'stall↓':>8}",
    ]
    for name, m in result.items():
        prem = f"{m['premature_advance_rate']:.0%}" if m["premature_advance_rate"] is not None else "  n/a"
        stall = f"{m['stall_rate']:.0%}" if m["stall_rate"] is not None else "  n/a"
        lines.append(
            f"  {name:<20} {m['accuracy_strict']:>6.0%} {m['accuracy_acceptable']:>6.0%}"
            f" {prem:>11} {stall:>8}"
        )
    first = next(iter(result.values()))
    lines += ["", f"  premature-advance denominator: {first['premature_advance_n']} items"
                  f"   stall denominator: {first['stall_n']} items"]
    return "\n".join(lines)
