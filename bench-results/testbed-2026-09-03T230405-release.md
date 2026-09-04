# Testbed run — 2026-09-03T23:04:05-05:00

**commit** `ad26a7165246` on `main`
**mode** live (model calls made) · python 3.13.4

## Suites

| suite | result | detail |
|---|---|---|
| offline | PASS | 213 passed, 0 failed, 0 errored, 0 skipped in 0.98s |
| e2e | PASS | 1 passed, 0 failed, 0 errored, 0 skipped in 0.55s |
| live | PASS | 5 passed, 0 failed, 0 errored, 0 skipped in 1.36s |
| **total** | | **219 tests passed** |
| coverage | 85% | statements |

## Dataset

- corpus items: **92** (weak labels) — {'follow_up': 72, 'synthesize': 11, 'advance': 5, 'refuse_and_continue': 4}
- synth items: **52** (spec labels) — {'follow_up': 33, 'advance': 19}
- minimal pairs: **12**
- human-adjudicated: **5**

## Gate evaluation

**synth** (n=52, premature denom 33, stall denom 19)

| policy | acc | premature ↓ | stall ↓ | minimal pairs |
|---|---|---|---|---|
| gate | 100% | 0% | 0% | 100% |
| always_follow_up | 63% | 0% | 100% | 0% |
| always_advance | 37% | 100% | 0% | 0% |
| budget_only | 88% | 0% | 32% | 0% |
| length_threshold | 56% | 30% | 68% | 33% |

**corpus** (n=92, premature denom 10, stall denom 2)

| policy | acc | premature ↓ | stall ↓ | minimal pairs |
|---|---|---|---|---|
| gate | 77% | 10% | 50% | n/a |
| always_follow_up | 78% | 0% | 100% | n/a |
| always_advance | 5% | 100% | 0% | n/a |
| budget_only | 66% | 10% | 50% | n/a |
| length_threshold | 47% | 100% | 50% | n/a |

**human** (n=5, premature denom 3, stall denom 2)

| policy | acc | premature ↓ | stall ↓ | minimal pairs |
|---|---|---|---|---|
| gate | 80% | 0% | 50% | n/a |
| always_follow_up | 60% | 0% | 100% | n/a |
| always_advance | 40% | 100% | 0% | n/a |
| budget_only | 80% | 0% | 50% | n/a |
| length_threshold | 60% | 67% | 0% | n/a |

## Assessors

| assessor | n | specificity | within 1 | ownership | both |
|---|---|---|---|---|---|
| deterministic | 23 | 74% | 100% | 96% | 70% |
| llm/haiku-4-5 | 23 | 91% | 100% | 65% | 65% |
| hybrid/haiku-4-5 | 23 | 91% | 100% | 96% | 87% |
| llm/sonnet-5 | 23 | 87% | 100% | 83% | 70% |
| hybrid/sonnet-5 | 23 | 87% | 100% | 96% | 83% |
| llm/opus-5 | 23 | 83% | 100% | 78% | 65% |
| hybrid/opus-5 | 23 | 83% | 100% | 96% | 78% |
| llm/gpt-4.1-mini | 23 | 74% | 100% | 83% | 61% |
| hybrid/gpt-4.1-mini | 23 | 74% | 100% | 96% | 70% |
| llm/gpt-4.1 | 23 | 78% | 100% | 87% | 65% |
| hybrid/gpt-4.1 | 23 | 78% | 100% | 96% | 78% |

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
    "pytest": "9.1.1"
  },
  "dataset_hashes": {
    "sufficiency.seed.jsonl": "0b107d7f45957839",
    "human_labels.jsonl": "7552f88cc312407b",
    "items.jsonl": "c566dfeba26bfa80",
    "labels.jsonl": "b4280d53fb978da4",
    "synth_items.jsonl": "96d1a029ef2d30a4",
    "synth_labels.jsonl": "c5eae593b800fa25"
  }
}
```
