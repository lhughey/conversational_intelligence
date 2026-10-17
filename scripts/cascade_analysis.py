"""Offline cascade analysis: would cheap-model-first, strong-model-on-escalation
beat a single-model assessor?

STRICTLY OFFLINE. Every model goes through `CachingLLM(mode="offline")`, which
raises on a miss instead of calling the API; a miss is counted and reported,
never filled by a live call. So this costs nothing and measures only what the
cache already holds.

Hybrid semantics throughout: ownership always comes from the rules
(DeterministicAssessor); only SPECIFICITY is cascaded. Per (cheap, strong) pair:

  cheap      cheap model alone
  strong     strong model alone
  oracle     escalate exactly where cheap's specificity is wrong (upper bound)
  disagree   escalate where cheap's specificity != the rules' specificity
  boundary   escalate where moving cheap's specificity one level up or down
             would flip the gate decision for that item
  union      disagree OR boundary

Datasets:
  (a) seed   23 hand-labelled turns (data/labels/sufficiency.seed.jsonl).
             There is no gate state here, so `boundary` uses the gate's
             sufficiency exit condition alone (`_gate_passes`), i.e. ASSUMES
             floor met, below ceiling, no user signal.
  (b) synth  the synth split end-to-end through the real `decide()` with each
             item's own budget/signal state.

Expected cost per item = cheap cost + escalation rate x strong cost, where a
model's per-call cost is the mean of `cost_usd(spec, usage)` over the cached
responses for that dataset.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from collections.abc import Callable, Hashable, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from convint.domain.enums import Specificity  # noqa: E402

CHEAP = ["haiku-5-5", "haiku-4-5"]
STRONG = ["sonnet-5-5", "opus-5-5"]
POLICY_NAMES = ["cheap", "strong", "oracle", "disagree", "boundary", "union"]
NOTE = "Offline cascade upper-bound from cached responses (no API calls)"

_BY_RANK = {s.rank: s for s in Specificity}


# --- pure trigger / escalation logic (unit-tested) ---------------------------

def neighbors(spec: Specificity) -> list[Specificity]:
    """Specificity one level down and one level up, clipped to S0..S3."""
    return [_BY_RANK[r] for r in (spec.rank - 1, spec.rank + 1) if r in _BY_RANK]


def oracle_trigger(cheap: Specificity, gold: Specificity) -> bool:
    return cheap is not gold


def disagree_trigger(cheap: Specificity, rule: Specificity) -> bool:
    return cheap is not rule


def boundary_trigger(cheap: Specificity, decide: Callable[[Specificity], Hashable]) -> bool:
    """True when a one-level error in cheap's specificity would change the decision."""
    here = decide(cheap)
    return any(decide(n) != here for n in neighbors(cheap))


def cascade(cheap: Sequence[Specificity], strong: Sequence[Specificity],
            escalate: Sequence[bool]) -> list[Specificity]:
    if not (len(cheap) == len(strong) == len(escalate)):
        raise ValueError("cheap, strong and escalate must be the same length")
    return [s if e else c for c, s, e in zip(cheap, strong, escalate)]


def triggers(cheap: Sequence[Specificity], gold: Sequence[Specificity],
             rule: Sequence[Specificity],
             deciders: Sequence[Callable[[Specificity], Hashable]]) -> dict[str, list[bool]]:
    """Escalation masks for every policy, one bool per item."""
    n = len(cheap)
    oracle = [oracle_trigger(c, g) for c, g in zip(cheap, gold)]
    disagree = [disagree_trigger(c, r) for c, r in zip(cheap, rule)]
    boundary = [boundary_trigger(c, d) for c, d in zip(cheap, deciders)]
    return {
        "cheap": [False] * n,
        "strong": [True] * n,
        "oracle": oracle,
        "disagree": disagree,
        "boundary": boundary,
        "union": [a or b for a, b in zip(disagree, boundary)],
    }


def expected_cost(policy: str, rate: float, cheap_cost: float, strong_cost: float) -> float:
    """Per item. Strong-alone never calls cheap; every cascade always does."""
    if policy == "strong":
        return strong_cost
    return cheap_cost + rate * strong_cost


# --- offline model collection -----------------------------------------------

class _UsageTap:
    """Sits OUTSIDE the cache so the cache key (inner adapter's model id) is
    unchanged; records the usage of every response it passes through."""

    def __init__(self, inner):
        self.inner = inner
        self.usages: list[dict] = []

    def complete(self, request):
        response = self.inner.complete(request)
        self.usages.append(dict(response.usage))
        return response


def collect(key: str, texts: list[str]) -> dict:
    """Specificity per text for one model from the cache only. Never spends."""
    from convint.adapters.assessor_llm import LLMAssessor
    from convint.adapters.cache import CacheMiss, CachingLLM
    from convint.adapters.models import build_llm, cost_usd, spec
    from convint.domain.sufficiency import SufficiencyComponents

    cache = CachingLLM(build_llm(key), mode="offline")
    tap = _UsageTap(cache)
    assessor = LLMAssessor(tap)  # effort="low" default, same as compare_assessors
    specs: dict[str, Specificity] = {}
    missing = 0
    for text in texts:
        try:
            specs[text] = assessor.assess(text, SufficiencyComponents()).specificity
        except CacheMiss:
            missing += 1
    costs = [cost_usd(spec(key), u) for u in tap.usages]
    return {"specs": specs, "hits": cache.hits, "misses": cache.misses,
            "missing": missing,
            "cost_per_call": sum(costs) / len(costs) if costs else None}


# --- datasets ------------------------------------------------------------------

class _Table:
    """An assessor that replays precomputed (specificity, ownership) by text."""

    def __init__(self, table: dict[str, tuple], name: str):
        self.table, self.name = table, name

    def assess(self, text, prior):
        from convint.domain.sufficiency import Assessment

        s, o = self.table[text]
        return Assessment(specificity=s, ownership=o, assessor=self.name)


def seed_dataset():
    from convint.adapters.assessor_deterministic import DeterministicAssessor
    from convint.bench.evaluate import load_labels, load_turn
    from convint.domain.gate import _gate_passes
    from convint.domain.sufficiency import SufficiencyComponents

    labels = load_labels()
    texts = [load_turn(l["transcript"], l["turn_index"]) for l in labels]
    if len(set(texts)) != len(texts):
        raise ValueError("seed texts are not unique; the by-text table would collide")
    rules = {t: DeterministicAssessor().assess(t, SufficiencyComponents()) for t in texts}
    gold = [Specificity(l["specificity"]) for l in labels]
    deciders = [(lambda s, o=rules[t].ownership: _gate_passes(s, o)) for t in texts]
    return {"labels": labels, "texts": texts, "rules": rules, "gold": gold,
            "deciders": deciders}


def synth_dataset():
    from convint.adapters.assessor_deterministic import DeterministicAssessor
    from convint.bench.gate_eval import _plan, _state
    from convint.dataset.synth import build_from_banks, minimal_pairs
    from convint.domain.gate import decide
    from convint.domain.sufficiency import SufficiencyComponents

    items, label_list = build_from_banks()
    labels = {l.item_id: l for l in label_list}
    pairs = minimal_pairs(items, label_list)
    texts = [i.text for i in items]
    unique = list(dict.fromkeys(texts))
    rules = {t: DeterministicAssessor().assess(t, SufficiencyComponents()) for t in unique}

    def decider(item):
        own = rules[item.text].ownership
        return lambda s: decide(_state(item, s, own), _plan(item)).action

    return {"items": items, "labels": labels, "pairs": pairs, "texts": texts,
            "unique": unique, "rules": rules,
            "gold": [i.specificity for i in items],
            "deciders": [decider(i) for i in items]}


def score_seed(ds, specs: list[Specificity], name: str) -> dict:
    from convint.bench.evaluate import evaluate

    table = {t: (s, ds["rules"][t].ownership) for t, s in zip(ds["texts"], specs)}
    r = evaluate(_Table(table, name), ds["labels"])
    keep = ("n", "clusters", "specificity_exact", "specificity_exact_ci",
            "both_exact", "both_exact_ci")
    return {k: r[k] for k in keep}


def score_synth(ds, specs: list[Specificity], name: str) -> dict:
    from convint.bench.gate_eval import _plan, _state, evaluate_policy
    from convint.domain.gate import decide

    by_id = {i.item_id: s for i, s in zip(ds["items"], specs)}

    def policy(item):
        own = ds["rules"][item.text].ownership
        return decide(_state(item, by_id[item.item_id], own), _plan(item)).action

    r = evaluate_policy(policy, ds["items"], ds["labels"], ds["pairs"])
    keep = ("n", "clusters", "accuracy_strict", "accuracy_strict_ci",
            "premature_advance_rate", "premature_advance_rate_ci",
            "stall_rate", "stall_rate_ci", "minimal_pair_accuracy",
            "minimal_pair_accuracy_ci")
    return {k: r[k] for k in keep}


def analyse(ds, model_specs: dict[str, dict], costs: dict[str, float], scorer) -> dict:
    """All policies for every (cheap, strong) pair on one dataset."""
    texts = ds["texts"]
    rule = [ds["rules"][t].specificity for t in texts]
    out: dict = {"deterministic": scorer(ds, rule, "deterministic")}
    for cheap in CHEAP:
        for strong in STRONG:
            pair = f"{cheap} -> {strong}"
            if cheap not in model_specs or strong not in model_specs:
                out[pair] = {"error": "model missing from cache"}
                continue
            c = [model_specs[cheap][t] for t in texts]
            s = [model_specs[strong][t] for t in texts]
            masks = triggers(c, ds["gold"], rule, ds["deciders"])
            rows = {}
            for policy in POLICY_NAMES:
                esc = masks[policy]
                rate = sum(esc) / len(esc)
                row = scorer(ds, cascade(c, s, esc), f"{policy}/{pair}")
                row["escalation_rate"] = rate
                row["cost_per_item_usd"] = expected_cost(
                    policy, rate, costs[cheap], costs[strong])
                rows[policy] = row
            out[pair] = rows
    return out


# --- rendering -------------------------------------------------------------------

def _ci(m: dict, k: str) -> str:
    from convint.bench.stats import format_ci

    return format_ci(m.get(k), m.get(f"{k}_ci"))


def _usd(x: float) -> str:
    return f"${x * 1000:.3f}/1k"


def render(results: dict) -> str:
    cache = results["cache"]
    lines = [
        "Offline only: every model call was served from `cache/` via "
        "`CachingLLM(mode=\"offline\")`; nothing was sent to an API.",
        "Hybrid semantics: ownership from DeterministicAssessor, only specificity cascaded.",
        "Cells are `rate [95% CI]`, cluster bootstrap (seed: transcripts; synth: topics).",
        "Cost is expected USD per item (shown per 1k items) = cheap + escalation x strong,",
        "per-call costs = mean cached usage x registry price.",
        "",
        "## Cache",
        "",
        "| model | seed hits | seed misses | synth hits | synth misses | seed $/call | synth $/call |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, c in cache.items():
        lines.append(
            f"| {key} | {c['seed']['hits']} | {c['seed']['misses']} | "
            f"{c['synth']['hits']} | {c['synth']['misses']} | "
            f"{c['seed']['cost_per_call'] or 0:.6f} | {c['synth']['cost_per_call'] or 0:.6f} |")

    lines += ["", "## (a) Seed set (23 items, k = transcripts)", "",
              "`boundary` on seed uses the sufficiency exit condition only "
              "(assumes floor met, below ceiling, no signal): the seed set carries no gate state.",
              "", f"deterministic: specificity {_ci(results['seed']['deterministic'], 'specificity_exact')}, "
              f"both {_ci(results['seed']['deterministic'], 'both_exact')}", ""]
    for pair, rows in results["seed"].items():
        if pair == "deterministic":
            continue
        lines += [f"### {pair}", ""]
        if "error" in rows:
            lines += [f"skipped: {rows['error']}", ""]
            continue
        lines += ["| policy | specificity | both | escalation | cost/item |",
                  "|---|---|---|---|---|"]
        for p, m in rows.items():
            lines.append(f"| {p} | {_ci(m, 'specificity_exact')} | {_ci(m, 'both_exact')} | "
                         f"{m['escalation_rate']:.0%} | {_usd(m['cost_per_item_usd'])} |")
        lines.append("")

    d = results["synth"]["deterministic"]
    lines += ["## (b) Synth split, end-to-end gate (k = topics)", "",
              f"deterministic: acc {_ci(d, 'accuracy_strict')}, premature "
              f"{_ci(d, 'premature_advance_rate')}, stall {_ci(d, 'stall_rate')}", ""]
    for pair, rows in results["synth"].items():
        if pair == "deterministic":
            continue
        lines += [f"### {pair}", ""]
        if "error" in rows:
            lines += [f"skipped: {rows['error']}", ""]
            continue
        lines += ["| policy | acc | premature | stall | pairs | escalation | cost/item |",
                  "|---|---|---|---|---|---|---|"]
        for p, m in rows.items():
            lines.append(f"| {p} | {_ci(m, 'accuracy_strict')} | "
                         f"{_ci(m, 'premature_advance_rate')} | {_ci(m, 'stall_rate')} | "
                         f"{_ci(m, 'minimal_pair_accuracy')} | {m['escalation_rate']:.0%} | "
                         f"{_usd(m['cost_per_item_usd'])} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def headline(results: dict) -> dict:
    out = {}
    for pair, rows in results["seed"].items():
        if pair == "deterministic" or "error" in rows:
            continue
        out[f"seed {pair} both"] = (
            f"strong {_ci(rows['strong'], 'both_exact')}, "
            f"oracle {_ci(rows['oracle'], 'both_exact')} @ {rows['oracle']['escalation_rate']:.0%}")
    for pair, rows in results["synth"].items():
        if pair == "deterministic" or "error" in rows:
            continue
        out[f"synth {pair} acc"] = (
            f"strong {_ci(rows['strong'], 'accuracy_strict')}, "
            f"oracle {_ci(rows['oracle'], 'accuracy_strict')} @ {rows['oracle']['escalation_rate']:.0%}")
    return out


def main(argv: list[str] | None = None) -> int:
    from convint.bench import record as recorder

    parser = argparse.ArgumentParser()
    parser.add_argument("--note", default=NOTE)
    parser.add_argument("--no-record", action="store_true")
    args = parser.parse_args(argv)
    prov = recorder.provenance()

    seed, synth = seed_dataset(), synth_dataset()
    cache: dict = {}
    specs: dict[str, dict] = {"seed": {}, "synth": {}}
    costs: dict[str, dict] = {"seed": {}, "synth": {}}
    for key in CHEAP + STRONG:
        cache[key] = {}
        for name, texts in (("seed", seed["texts"]), ("synth", synth["unique"])):
            got = collect(key, texts)
            cache[key][name] = {k: got[k] for k in ("hits", "misses", "missing", "cost_per_call")}
            print(f"{key:<11} {name:<5} hits={got['hits']} misses={got['misses']}")
            if got["missing"] == 0:
                specs[name][key] = got["specs"]
                costs[name][key] = got["cost_per_call"]

    results = {
        "cache": cache,
        "seed": analyse(seed, specs["seed"], costs["seed"], score_seed),
        "synth": analyse(synth, specs["synth"], costs["synth"], score_synth),
        "synth_unique_texts": len(synth["unique"]),
    }
    text = render(results)
    print(text)
    if not args.no_record:
        paths = recorder.record_run(
            "cascade-offline", args.note, results, text,
            models=[recorder.assessor_model_label(k) for k in CHEAP + STRONG],
            headline=headline(results), cost="$0 (offline cache)", prov=prov,
        )
        print(f"recorded -> {paths['md'].name} (and HISTORY.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
