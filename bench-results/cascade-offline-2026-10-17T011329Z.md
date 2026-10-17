# cascade-offline run — 2026-10-17T01:13:29+00:00

> **What this run tested:** Offline cascade upper-bound from cached responses (no API calls)

- **command** `scripts/cascade_analysis.py`
- **commit** `a7c4c57c2755` on `main`  ⚠️ **DIRTY TREE — not reproducible from the commit alone**
- **python** 3.13.4
- **models / effort** haiku-5-5 (claude-haiku-5-5, effort low), haiku-4-5 (claude-haiku-4-5, effort n/a), sonnet-5-5 (claude-sonnet-5-5, effort low), opus-5-5 (claude-opus-5-5, effort low)
- **est. cost** $0 (offline cache)

**Headline**

- seed haiku-5-5 -> sonnet-5-5 both: strong 91% [67–100], oracle 91% [67–100] @ 13%
- seed haiku-5-5 -> opus-5-5 both: strong 87% [67–97], oracle 91% [67–100] @ 13%
- seed haiku-4-5 -> sonnet-5-5 both: strong 91% [67–100], oracle 96% [81–100] @ 9%
- seed haiku-4-5 -> opus-5-5 both: strong 87% [67–97], oracle 96% [81–100] @ 9%
- synth haiku-5-5 -> sonnet-5-5 acc: strong 92% [86–100], oracle 92% [86–100] @ 46%
- synth haiku-5-5 -> opus-5-5 acc: strong 92% [86–100], oracle 92% [86–100] @ 46%
- synth haiku-4-5 -> sonnet-5-5 acc: strong 92% [86–100], oracle 92% [86–100] @ 23%
- synth haiku-4-5 -> opus-5-5 acc: strong 92% [86–100], oracle 92% [86–100] @ 23%

---
Offline only: every model call was served from `cache/` via `CachingLLM(mode="offline")`; nothing was sent to an API.
Hybrid semantics: ownership from DeterministicAssessor, only specificity cascaded.
Cells are `rate [95% CI]`, cluster bootstrap (seed: transcripts; synth: topics).
Cost is expected USD per item (shown per 1k items) = cheap + escalation x strong,
per-call costs = mean cached usage x registry price.

## Cache

| model | seed hits | seed misses | synth hits | synth misses | seed $/call | synth $/call |
|---|---|---|---|---|---|---|
| haiku-5-5 | 23 | 0 | 13 | 0 | 0.000203 | 0.000171 |
| haiku-4-5 | 23 | 0 | 13 | 0 | 0.001388 | 0.001389 |
| sonnet-5-5 | 23 | 0 | 13 | 0 | 0.003447 | 0.003418 |
| opus-5-5 | 23 | 0 | 13 | 0 | 0.006750 | 0.006773 |

## (a) Seed set (23 items, k = transcripts)

`boundary` on seed uses the sufficiency exit condition only (assumes floor met, below ceiling, no signal): the seed set carries no gate state.

deterministic: specificity 74% [53–90], both 70% [50–81]

### haiku-5-5 -> sonnet-5-5

| policy | specificity | both | escalation | cost/item |
|---|---|---|---|---|
| cheap | 87% [67–96] | 83% [50–96] | 0% | $0.203/1k |
| strong | 96% [81–100] | 91% [67–100] | 100% | $3.447/1k |
| oracle | 96% [81–100] | 91% [67–100] | 13% | $0.653/1k |
| disagree | 91% [79–100] | 87% [67–96] | 26% | $1.103/1k |
| boundary | 91% [67–100] | 87% [50–100] | 9% | $0.503/1k |
| union | 96% [81–100] | 91% [67–100] | 30% | $1.253/1k |

### haiku-5-5 -> opus-5-5

| policy | specificity | both | escalation | cost/item |
|---|---|---|---|---|
| cheap | 87% [67–96] | 83% [50–96] | 0% | $0.203/1k |
| strong | 91% [75–100] | 87% [67–97] | 100% | $6.750/1k |
| oracle | 96% [81–100] | 91% [67–100] | 13% | $1.084/1k |
| disagree | 91% [79–100] | 87% [67–96] | 26% | $1.964/1k |
| boundary | 91% [67–100] | 87% [50–100] | 9% | $0.790/1k |
| union | 96% [81–100] | 91% [67–100] | 30% | $2.258/1k |

### haiku-4-5 -> sonnet-5-5

| policy | specificity | both | escalation | cost/item |
|---|---|---|---|---|
| cheap | 91% [79–100] | 87% [62–100] | 0% | $1.388/1k |
| strong | 96% [81–100] | 91% [67–100] | 100% | $3.447/1k |
| oracle | 100% [100–100] | 96% [81–100] | 9% | $1.688/1k |
| disagree | 96% [81–100] | 91% [67–100] | 35% | $2.587/1k |
| boundary | 87% [67–96] | 83% [50–96] | 13% | $1.838/1k |
| union | 96% [81–100] | 91% [67–100] | 35% | $2.587/1k |

### haiku-4-5 -> opus-5-5

| policy | specificity | both | escalation | cost/item |
|---|---|---|---|---|
| cheap | 91% [79–100] | 87% [62–100] | 0% | $1.388/1k |
| strong | 91% [75–100] | 87% [67–97] | 100% | $6.750/1k |
| oracle | 100% [100–100] | 96% [81–100] | 9% | $1.975/1k |
| disagree | 96% [81–100] | 91% [67–100] | 35% | $3.736/1k |
| boundary | 87% [67–96] | 83% [50–96] | 13% | $2.268/1k |
| union | 96% [81–100] | 91% [67–100] | 35% | $3.736/1k |

## (b) Synth split, end-to-end gate (k = topics)

deterministic: acc 88% [80–97], premature 0% [0–0], stall 32% [12–44]

### haiku-5-5 -> sonnet-5-5

| policy | acc | premature | stall | pairs | escalation | cost/item |
|---|---|---|---|---|---|---|
| cheap | 88% [80–97] | 0% [0–0] | 32% [12–44] | 0% [0–0] | 0% | $0.171/1k |
| strong | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 100% | $3.418/1k |
| oracle | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 46% | $1.749/1k |
| disagree | 88% [80–97] | 0% [0–0] | 32% [12–44] | 0% [0–0] | 46% | $1.749/1k |
| boundary | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 12% | $0.566/1k |
| union | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 54% | $2.012/1k |

### haiku-5-5 -> opus-5-5

| policy | acc | premature | stall | pairs | escalation | cost/item |
|---|---|---|---|---|---|---|
| cheap | 88% [80–97] | 0% [0–0] | 32% [12–44] | 0% [0–0] | 0% | $0.171/1k |
| strong | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 100% | $6.773/1k |
| oracle | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 46% | $3.298/1k |
| disagree | 88% [80–97] | 0% [0–0] | 32% [12–44] | 0% [0–0] | 46% | $3.298/1k |
| boundary | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 12% | $0.953/1k |
| union | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 54% | $3.819/1k |

### haiku-4-5 -> sonnet-5-5

| policy | acc | premature | stall | pairs | escalation | cost/item |
|---|---|---|---|---|---|---|
| cheap | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 0% | $1.389/1k |
| strong | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 100% | $3.418/1k |
| oracle | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 23% | $2.177/1k |
| disagree | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 38% | $2.703/1k |
| boundary | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 12% | $1.783/1k |
| union | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 42% | $2.835/1k |

### haiku-4-5 -> opus-5-5

| policy | acc | premature | stall | pairs | escalation | cost/item |
|---|---|---|---|---|---|---|
| cheap | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 0% | $1.389/1k |
| strong | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 100% | $6.773/1k |
| oracle | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 23% | $2.952/1k |
| disagree | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 38% | $3.994/1k |
| boundary | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 12% | $2.170/1k |
| union | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 42% | $4.254/1k |

