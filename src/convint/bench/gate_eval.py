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

from ..domain.enums import Action, Ownership, Specificity
from ..domain.gate import decide
from ..domain.plan import Budget, InterviewPlan, StageSpec, TopicSpec
from ..domain.state import ConversationState, TopicRecord, Turn
from ..domain.sufficiency import SufficiencyComponents
from ..dataset.build import load
from ..dataset.schema import Item, Label
from ..dataset.synth import minimal_pairs
from .stats import format_ci, rate_summary


def _plan(item: Item) -> InterviewPlan:
    return InterviewPlan(
        plan_id="eval",
        stages=[StageSpec(stage_id="s", completion_signal="stage_complete")],
        topics=[TopicSpec(topic_id="t", stage="s",
                          budget=Budget(floor=item.floor, ceiling=item.ceiling))],
    )


def _state(item: Item, specificity: Specificity | None = None,
           ownership: Ownership | None = None) -> ConversationState:
    """Gate input for one item. Without overrides the topic carries the item's
    own (authored or build-time) specificity/ownership - the ORACLE inputs."""
    return ConversationState(
        turns=[Turn(role="user", content=item.text)],
        topics=[TopicRecord(
            topic_id="t", stage="s", followups_used=item.followups_used,
            specificity=item.specificity if specificity is None else specificity,
            ownership=item.ownership if ownership is None else ownership,
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


class E2EGatePolicy:
    """The gate fed by an assessor instead of the authored labels.

    On the synth split the oracle `gate_policy` reads each rung's AUTHORED
    specificity/ownership, so it measures rule-following with perfect inputs.
    This policy runs `assessor` on the item text first and decides on what it
    returns - the end-to-end number, where assessor error propagates into
    the decision. Any `SufficiencyAssessor` works (deterministic, LLM, hybrid).

    The assessor sees `item.text` with an empty prior: synth gold is authored
    per rung, so that is the like-for-like comparison. Assessments are memoised
    by text because each rung appears once per budget state.
    """

    def __init__(self, assessor):
        self.assessor = assessor
        self.name = getattr(assessor, "name", type(assessor).__name__)
        self._seen: dict[str, tuple[Specificity, Ownership]] = {}

    def assess(self, item: Item) -> tuple[Specificity, Ownership]:
        if item.text not in self._seen:
            a = self.assessor.assess(item.text, SufficiencyComponents())
            self._seen[item.text] = (a.specificity, a.ownership)
        return self._seen[item.text]

    def __call__(self, item: Item) -> Action:
        spec, own = self.assess(item)
        return decide(_state(item, spec, own), _plan(item)).action


def make_assessor(spec: str = "deterministic"):
    """Build an assessor from `deterministic`, `llm:<key>` or `hybrid:<key>`.

    Model-backed assessors follow scripts/compare_assessors.py: a registry key
    through `build_llm`, wrapped in a read-write `CachingLLM`. Constructing one
    makes no call; evaluating it does (and costs money on a cache miss).
    Spec parsing is shared with the serving path (`app/engine_factory.py`),
    which does NOT cache - the response cache is a bench tool.
    """
    from ..adapters.cache import CachingLLM
    from ..app.engine_factory import assessor_from_spec

    return assessor_from_spec(spec, wrap=lambda llm: CachingLLM(llm, mode="rw"))


def e2e_key(assessor_name: str) -> str:
    return f"gate (e2e: {assessor_name})"


POLICIES = {
    "gate": gate_policy,
    "always_follow_up": always_follow_up,
    "always_advance": always_advance,
    "budget_only": budget_only,
    "length_threshold": length_threshold,
}


# --- metrics ---------------------------------------------------------------

def cluster_key(item: Item) -> str:
    """The resampling unit for confidence intervals.

    Corpus (and human, which is a subset of corpus) items: the TRANSCRIPT.
    Turns within one golden share a persona and an author, so they are
    correlated; effective n is about the number of transcripts.

    Synth items all come from one persona (`transcript="bank:maya"`), so the
    transcript is a single cluster and would give no interval at all. The next
    unit down is the bank TOPIC (`maya/childhood.dry_cleaner`): every item of a
    topic reuses that topic's few rung texts across budget states, so items
    within a topic are near-duplicates, while topics are separately authored.
    Minimal pairs are formed within (topic, budget) and so never straddle two
    clusters. The price is honesty about size: k = 4 topics today.
    """
    if item.transcript.startswith("bank:"):
        return item.item_id.split("#")[0]
    return item.transcript


def cluster_unit(items: list[Item]) -> str:
    return "topics" if items and items[0].transcript.startswith("bank:") else "transcripts"


def evaluate_policy(policy, items: list[Item], labels: dict[str, Label],
                    pairs: list[tuple[str, str]] | None = None,
                    *, seed: int = 0, n_boot: int = 2000) -> dict:
    """Score one policy. Every rate comes with `<rate>_ci` ([lo, hi] or None),
    `<rate>_n` (its denominator) and `<rate>_k` (clusters behind it)."""
    strict, accept, clusters = [], [], []
    prem, prem_c, stall, stall_c = [], [], [], []
    predictions: dict[str, Action] = {}

    for item in items:
        label = labels[item.item_id]
        predicted = policy(item)
        predictions[item.item_id] = predicted
        cid = cluster_key(item)
        clusters.append(cid)

        strict.append(predicted is label.action)
        accept.append(label.is_correct(predicted))

        # must-follow-up items: advancing here is the failure under study
        if label.action is Action.FOLLOW_UP and Action.ADVANCE not in label.acceptable:
            prem.append(predicted in (Action.ADVANCE, Action.SYNTHESIZE))
            prem_c.append(cid)

        # must-advance items: refusing to move on is the mirror failure
        if label.action is Action.ADVANCE and Action.FOLLOW_UP not in label.acceptable:
            stall.append(predicted is Action.FOLLOW_UP)
            stall_c.append(cid)

    pair_ok, pair_c = [], []
    if pairs:
        by_id = {i.item_id: i for i in items}
        for a, b in pairs:
            if a in predictions and b in predictions:
                pair_ok.append(
                    labels[a].is_correct(predictions[a])
                    and labels[b].is_correct(predictions[b])
                )
                pair_c.append(cluster_key(by_id[a]))

    boot = {"seed": seed, "n_boot": n_boot}
    rates = {
        "accuracy_strict": rate_summary(strict, clusters, **boot),
        "accuracy_acceptable": rate_summary(accept, clusters, **boot),
        "premature_advance_rate": rate_summary(prem, prem_c, **boot),
        "stall_rate": rate_summary(stall, stall_c, **boot),
        "minimal_pair_accuracy": rate_summary(pair_ok, pair_c, **boot),
    }

    n = len(items)
    out = {
        "n": n,
        "clusters": len(set(clusters)),
        "cluster_unit": cluster_unit(items),
        "minimal_pair_accuracy": rates["minimal_pair_accuracy"]["rate"],
        "minimal_pair_n": len(pair_ok),
        "accuracy_strict": sum(strict) / n,
        "accuracy_acceptable": sum(accept) / n,
        "premature_advance_rate": rates["premature_advance_rate"]["rate"],
        "premature_advance_n": len(prem),
        "stall_rate": rates["stall_rate"]["rate"],
        "stall_n": len(stall),
    }
    for metric, r in rates.items():
        out[f"{metric}_ci"] = r["ci"]
        out[f"{metric}_n"] = r["n"]
        out[f"{metric}_k"] = r["k"]
    return out


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


def run(split: str = "synth", e2e_assessor=None) -> dict:
    """Evaluate on one split. `synth` is balanced and carries minimal pairs;
    `corpus` is realistic but skewed and weakly labelled.

    With `e2e_assessor`, one extra row `gate (e2e: <name>)` is added beside the
    oracle `gate` row: the same gate, fed by that assessor instead of the
    authored inputs. Synth only - corpus items are already built by running
    the deterministic assessor over each transcript (dataset/build.py), so on
    corpus the plain `gate` row is already end-to-end."""
    if e2e_assessor is not None and split != "synth":
        raise ValueError(
            "end-to-end mode applies to the synth split only; corpus/human items "
            "already carry assessor-derived state, so their gate row is end-to-end"
        )
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
    result = {}
    for name, fn in POLICIES.items():
        result[name] = evaluate_policy(fn, items, labels, pairs)
        if name == "gate" and e2e_assessor is not None:
            policy = E2EGatePolicy(e2e_assessor)
            row = evaluate_policy(policy, items, labels, pairs)
            assessed = [policy.assess(i) for i in items]
            # How far the assessor's inputs are from the authored ones - the
            # cause of any gap between the oracle and e2e rows.
            row["assessor_specificity_agreement"] = sum(
                a[0] is i.specificity for a, i in zip(assessed, items)) / len(items)
            row["assessor_ownership_agreement"] = sum(
                a[1] is i.ownership for a, i in zip(assessed, items)) / len(items)
            result[e2e_key(policy.name)] = row
    return result


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


def _cell(m: dict, metric: str) -> str:
    return format_ci(m[metric], m[f"{metric}_ci"])


def format_report(result: dict, split: str = "synth") -> str:
    """Each cell is `rate [95% CI]`; denominators and cluster counts follow the
    table, because they are a property of the labels, not of the policy."""
    lines = [
        f"gate evaluation — split: {split}",
        f"  {PROVENANCE.get(split, '')}",
        "",
    ]
    e2e = any(name.startswith("gate (e2e") for name in result)
    shown = {n: f"{n} (oracle inputs)" if e2e and n == "gate" else n for n in result}
    width = max(20, *(len(v) for v in shown.values()))
    cols = [("accuracy_strict", "acc"), ("premature_advance_rate", "premature↓"),
            ("stall_rate", "stall↓"), ("minimal_pair_accuracy", "pairs")]
    lines.append(f"  {'policy':<{width}} " + " ".join(f"{h:>14}" for _, h in cols))
    for name, m in result.items():
        lines.append(f"  {shown[name]:<{width}} "
                     + " ".join(f"{_cell(m, c):>14}" for c, _ in cols))

    first = next(iter(result.values()))
    unit = first.get("cluster_unit", "transcripts")
    lines += ["", "  95% cluster-bootstrap CI in brackets ([—] = fewer than 2 clusters);"
                  " denominators:"]
    for metric, header in cols:
        n = first.get(f"{metric}_n", first["n"])
        lines.append(f"    {header:<11} n={n} (k={first.get(f'{metric}_k', '?')} {unit})")
    for name, m in result.items():
        if "assessor_specificity_agreement" in m:
            lines.append(
                f"  {name}: assessor matches authored specificity on "
                f"{m['assessor_specificity_agreement']:.0%} of items, ownership on "
                f"{m['assessor_ownership_agreement']:.0%}"
            )
    return "\n".join(lines)
