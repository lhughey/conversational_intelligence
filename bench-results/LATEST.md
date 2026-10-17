# testbed run — 2026-10-17T00:42:00+00:00

> **What this run tested:** Full live testbed after model refresh (5.5 registry), CIs, e2e gate, truncation fix, run recorder

- **command** `scripts/testbed.py --live --note 'Full live testbed after model refresh (5.5 registry), CIs, e2e gate, truncation fix, run recorder'`
- **commit** `a7c4c57c2755` on `main`  ⚠️ **DIRTY TREE — not reproducible from the commit alone**
- **python** 3.13.4
- **models / effort** haiku-4-5 (claude-haiku-4-5, effort n/a), haiku-5-5 (claude-haiku-5-5, effort low), sonnet-5 (claude-sonnet-5, effort low), sonnet-5-5 (claude-sonnet-5-5, effort low), opus-5 (claude-opus-5, effort low), opus-5-5 (claude-opus-5-5, effort low), gpt-4.1-mini (gpt-4.1-mini, effort n/a), gpt-4.1 (gpt-4.1, effort n/a), invariants: haiku-4-5 (generator, effort n/a)

**Headline**

- suites: offline PASS (287 passed), e2e PASS (1 passed), live PASS (5 passed)
- synth gate: acc 100% [100–100], premature 0% [0–0], stall 0% [0–0]
- synth gate (e2e: deterministic): acc 88% [80–97], premature 0% [0–0], stall 32% [12–44]
- corpus gate: acc 77% [73–81], premature 10% [0–38], stall 50% [0–100]
- human gate: acc 80% [57–100], premature 0% [0–0], stall 50% [0–100]
- invariants: single-question 100%, grounded 100% of 6 samples
- best assessor (both): hybrid/sonnet-5-5 91% [67–100]

---
**mode** live (model calls made) · macOS-27.0.1-arm64-arm-64bit-Mach-O

## Suites

| suite | result | detail |
|---|---|---|
| offline | PASS | 287 passed, 0 failed, 0 errored, 0 skipped in 2.43s |
| e2e | PASS | 1 passed, 0 failed, 0 errored, 0 skipped in 0.54s |
| live | PASS | 5 passed, 0 failed, 0 errored, 0 skipped in 1.18s |
| **total** | | **293 tests passed** |
| coverage | 86% | statements |

## Dataset

- corpus items: **92** (weak labels) — {'follow_up': 72, 'synthesize': 11, 'advance': 5, 'refuse_and_continue': 4}
- synth items: **52** (spec labels) — {'follow_up': 33, 'advance': 19}
- minimal pairs: **12**
- human-adjudicated: **5**

## Gate evaluation

Cells are `rate [95% CI]`, a cluster bootstrap over transcripts (synth: over
bank topics, since it is one persona). `[—]` = fewer than 2 clusters, no
interval. Denominators `n` and cluster counts `k` sit under each table.

**synth**

| policy | acc | premature ↓ | stall ↓ | minimal pairs |
|---|---|---|---|---|
| gate (oracle inputs) | 100% [100–100] | 0% [0–0] | 0% [0–0] | 100% [100–100] |
| gate (e2e: deterministic) | 88% [80–97] | 0% [0–0] | 32% [12–44] | 0% [0–0] |
| always_follow_up | 63% [55–72] | 0% [0–0] | 100% [100–100] | 0% [0–0] |
| always_advance | 37% [28–45] | 100% [100–100] | 0% [0–0] | 0% [0–0] |
| budget_only | 88% [80–97] | 0% [0–0] | 32% [12–44] | 0% [0–0] |
| length_threshold | 56% [50–67] | 30% [9–45] | 68% [44–90] | 33% [0–100] |

denominators: acc n=52 (k=4 topics) · premature ↓ n=33 (k=4 topics) · stall ↓ n=19 (k=4 topics) · minimal pairs n=12 (k=3 topics)

gate (e2e: deterministic): assessor matches authored specificity on 38% of items, ownership on 92%.

**corpus**

| policy | acc | premature ↓ | stall ↓ | minimal pairs |
|---|---|---|---|---|
| gate | 77% [73–81] | 10% [0–38] | 50% [0–100] | n/a |
| always_follow_up | 78% [69–85] | 0% [0–0] | 100% [100–100] | n/a |
| always_advance | 5% [0–11] | 100% [100–100] | 0% [0–0] | n/a |
| budget_only | 66% [60–72] | 10% [0–38] | 50% [0–100] | n/a |
| length_threshold | 47% [37–58] | 100% [100–100] | 50% [0–100] | n/a |

denominators: acc n=92 (k=11 transcripts) · premature ↓ n=10 (k=4 transcripts) · stall ↓ n=2 (k=2 transcripts) · minimal pairs n=0 (k=0 transcripts)

**human**

| policy | acc | premature ↓ | stall ↓ | minimal pairs |
|---|---|---|---|---|
| gate | 80% [57–100] | 0% [0–0] | 50% [0–100] | n/a |
| always_follow_up | 60% [25–100] | 0% [0–0] | 100% [100–100] | n/a |
| always_advance | 40% [0–75] | 100% [100–100] | 0% [0–0] | n/a |
| budget_only | 80% [57–100] | 0% [0–0] | 50% [0–100] | n/a |
| length_threshold | 60% [25–100] | 67% [0–100] | 0% [0–0] | n/a |

denominators: acc n=5 (k=4 transcripts) · premature ↓ n=3 (k=3 transcripts) · stall ↓ n=2 (k=2 transcripts) · minimal pairs n=0 (k=0 transcripts)

## Assessors

Cells are `rate [95% CI]`, a cluster bootstrap over the seed set's transcripts.

| assessor | n (k) | specificity | within 1 | ownership | both |
|---|---|---|---|---|---|
| deterministic | 23 (k=4) | 74% [53–90] | 100% [100–100] | 96% [81–100] | 70% [50–81] |
| llm/haiku-4-5 | 23 (k=4) | 91% [79–100] | 100% [100–100] | 65% [42–92] | 65% [42–92] |
| hybrid/haiku-4-5 | 23 (k=4) | 91% [79–100] | 100% [100–100] | 96% [81–100] | 87% [62–100] |
| llm/haiku-5-5 | 23 (k=4) | 87% [67–96] | 96% [81–100] | 65% [46–90] | 61% [42–80] |
| hybrid/haiku-5-5 | 23 (k=4) | 87% [67–96] | 96% [81–100] | 96% [81–100] | 83% [50–96] |
| llm/sonnet-5 | 23 (k=4) | 87% [75–94] | 100% [100–100] | 83% [69–100] | 70% [61–83] |
| hybrid/sonnet-5 | 23 (k=4) | 87% [75–94] | 100% [100–100] | 96% [81–100] | 83% [67–88] |
| llm/sonnet-5-5 | 23 (k=4) | 96% [81–100] | 100% [100–100] | 78% [53–100] | 74% [50–92] |
| hybrid/sonnet-5-5 | 23 (k=4) | 96% [81–100] | 100% [100–100] | 96% [81–100] | 91% [67–100] |
| llm/opus-5 | 23 (k=4) | 83% [67–88] | 100% [100–100] | 78% [67–96] | 65% [47–80] |
| hybrid/opus-5 | 23 (k=4) | 83% [67–88] | 100% [100–100] | 96% [81–100] | 78% [50–88] |
| llm/opus-5-5 | 23 (k=4) | 91% [75–100] | 100% [100–100] | 78% [53–100] | 70% [50–81] |
| hybrid/opus-5-5 | 23 (k=4) | 91% [75–100] | 100% [100–100] | 96% [81–100] | 87% [67–97] |
| llm/gpt-4.1-mini | 23 (k=4) | 74% [67–79] | 100% [100–100] | 83% [56–94] | 61% [44–69] |
| hybrid/gpt-4.1-mini | 23 (k=4) | 74% [67–79] | 100% [100–100] | 96% [81–100] | 70% [50–78] |
| llm/gpt-4.1 | 23 (k=4) | 78% [50–100] | 100% [100–100] | 87% [75–100] | 65% [25–85] |
| hybrid/gpt-4.1 | 23 (k=4) | 78% [50–100] | 100% [100–100] | 96% [81–100] | 78% [50–100] |

## Generation invariants (live, cache off)

Measured over 6 fresh samples, because sampling is not
tunable on these models and a single draw cannot establish a rate.

| property | rate |
|---|---|
| exactly one question | 100% |
| ends with the question | 100% |
| grounded in the user's words | 100% |
| mean length | 13 words |


## Corpus replay

11 transcripts, 92 turns

- actions: `{'follow_up': 63, 'advance': 19, 'synthesize': 6, 'refuse_and_continue': 4}`
- rules fired: `{'default_deepen': 33, 'floor_not_met': 25, 'ceiling_reached': 14, 'closing_honest_shortfall': 6, 'no_content_redirect': 5, 'adversarial_input': 4, 'gate_met': 4, 'acknowledgment_signpost': 1}`

## Provenance

```json
{
  "packages": {
    "pydantic": "2.13.5",
    "anthropic": "1.3.0",
    "openai": "3.8.0",
    "fastapi": "0.141.1",
    "pytest": "9.1.1",
    "convint": "0.1.0"
  },
  "dataset_hashes": {
    "labels/sufficiency.seed.jsonl": "0b107d7f45957839",
    "turn_decisions/human_labels.jsonl": "7552f88cc312407b",
    "turn_decisions/items.jsonl": "c566dfeba26bfa80",
    "turn_decisions/labels.jsonl": "b4280d53fb978da4",
    "turn_decisions/synth_items.jsonl": "96d1a029ef2d30a4",
    "turn_decisions/synth_labels.jsonl": "c5eae593b800fa25"
  }
}
```
