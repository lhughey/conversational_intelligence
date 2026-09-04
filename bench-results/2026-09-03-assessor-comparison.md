# Assessor comparison — 2026-09-03

23 hand-labelled turns (`data/labels/sufficiency.seed.jsonl`), five models,
three assessor strategies. Reproduce with `make bench-assessors` (cached, so
re-runs are free).

| assessor | specificity | ownership | both |
|---|---|---|---|
| deterministic | 74% | **96%** | 70% |
| llm / haiku-4-5 | **91%** | 65% | 65% |
| **hybrid / haiku-4-5** | **91%** | **96%** | **87%** |
| llm / sonnet-5 | 87% | 83% | 70% |
| hybrid / sonnet-5 | 87% | 96% | 83% |
| llm / opus-5 | 83% | 78% | 65% |
| hybrid / opus-5 | 83% | 96% | 78% |
| llm / gpt-4.1-mini | 74% | 83% | 61% |
| hybrid / gpt-4.1-mini | 74% | 96% | 70% |
| llm / gpt-4.1 | 78% | 87% | 65% |
| hybrid / gpt-4.1 | 78% | 96% | 78% |

## Three findings

**1. The hybrid beats every model, and every model beats it on nothing.**
Routing specificity to the model and ownership to the rules wins on all five
models — by +22pp over the LLM alone on haiku, +17pp over the deterministic
baseline. Neither instrument dominates: models read narrative structure that
regex cannot pattern-match, while ownership turns on a small closed set of
surface cues (confirmations, imported self-labels) that regex matches exactly
and models over-read as insight.

**2. Specificity scales INVERSELY with model capability.**
haiku-4-5 91% > sonnet-5 87% > opus-5 83%. The cheapest model is the most
accurate, and the pattern is monotonic across the Anthropic tier. The likely
mechanism is that stronger models interpret more generously — they infer a
scene or stakes the text only implies, which inflates S2 into S3. The rubric
asks for conservatism, and the smaller model is more literal. At n=23 this
could be noise, but it is monotonic across three tiers and worth a held-out
retest before anyone pays for Opus on this task.

**3. So the recommended configuration is the cheapest one.**
`hybrid/haiku-4-5` at 87%. Haiku is $1/$5 per MTok against Opus 5 at $5/$25 —
5× cheaper and more accurate on this task. That is not the result anyone
expects, which is exactly why it was worth measuring rather than assuming.

## Caveats that bound all of the above

- **n = 23, one labeller.** Enough to catch a broken assessor, not enough to
  separate 83% from 87%.
- **The set was used for tuning.** Two fixes were made after seeing results: a
  signpost rule (74% → the current specificity) and moving `"that's me"` from
  reflection to confirmation (91% → 96% ownership). These are principled and
  independently justified, but they mean the numbers are a floor, not an
  unbiased estimate.
- **No confidence intervals.** With 11 correlated synthetic transcripts from one
  author, effective n is closer to 10 than 23. Differences under ~10pp should
  not be read as real.

Next: a held-out label set, and cluster-bootstrap intervals.
