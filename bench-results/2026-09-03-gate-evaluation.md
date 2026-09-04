# Gate evaluation — 2026-09-03

92 turn-decision items built from the 11 golden transcripts
(`convint dataset build`), scored against **weak** labels.

| policy | acc | acc (acceptable-set) | premature advance ↓ | stall ↓ |
|---|---|---|---|---|
| gate | 60% | **91%** | 40% | 50% |
| always_follow_up | **78%** | 82% | **0%** | **100%** |
| always_advance | 5% | 85% | 100% | 0% |
| budget_only | 49% | 86% | 40% | 50% |
| length_threshold | 47% | 72% | 100% | 50% |

Denominators: 10 must-follow-up items, 2 must-advance items.

## What this says

**The metric pair works.** `always_follow_up` scores a perfect 0% premature
advance and a catastrophic 100% stall; `always_advance` is the mirror. Either
number alone is trivially gameable, which is why they are always reported
adjacent. The gate is the only policy that sits between the extremes on both.

**But the dataset cannot yet demonstrate the gate's value.** `always_follow_up`
beats the gate on strict accuracy (78% vs 60%). That is a property of the
corpus, not a defence of the naive policy: 72 of 92 weak labels are
`follow_up`, because every golden transcript was authored to punish premature
advance and none was authored to punish stalling. The stall denominator is
**2 items** — far too small to mean anything.

**The labels are weak.** They are inferred from each transcript's own next user
turn — what the author implicitly assumed the interviewer had asked — not from
independent judgement. Every label carries `source="weak"`. No number here
should be quoted as an accuracy until adjudicated.

## Concrete next steps

1. Author fixtures where **advancing is the correct move** from a thin answer.
   Until those exist the benchmark is structurally biased toward always-follow-up.
2. Human-adjudicate the 92 weak labels; record inter-annotator agreement.
3. Add cluster-bootstrap intervals at the transcript level (effective n ≈ 11,
   not 92).
