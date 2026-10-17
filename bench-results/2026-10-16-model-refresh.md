# Model refresh — 2026-10-16

A summary for the historical record. Every number below is copied from a
recorded run file in this directory; the file is cited next to each table. All
runs measured commit `a7c4c57` with uncommitted changes (`+dirty`), so they are
reproducible from the working tree of that day, not from the commit alone.

## What was tested and why

The Sept 3 baseline (`2026-09-03-assessor-comparison.md`) compared five models:
haiku-4-5, sonnet-5, opus-5, gpt-4.1-mini, gpt-4.1. Since then the 5.5
generation became available and was added to the registry
(`src/convint/adapters/models.py`):

| model | price in / out (per MTok) | notes |
|---|---|---|
| opus-5-5 | $4 / $20 | API default effort is `medium`; pinned to `effort=high` in non-assessor paths (generator, artifact builder) |
| sonnet-5-5 | $2 / $10 | |
| haiku-5-5 | $0.10 / $0.50 | price applies to prompts ≤100k tokens; uses ~30% more tokens than haiku-4-5 for the same text |
| fable-5-1 | — | registered, not benchmarked (cost) |

Registry fixes in the same change: sonnet-5's price was corrected from $3/$15
to $2/$10. **The assessor always runs at `effort=low`**, on every model that
accepts effort (haiku-4-5 and the GPT models do not; they show `effort n/a`).

The questions: do the 5.5 models change which assessor is best, and does the
gate still hold up when its inputs come from a real assessor rather than from
the authored labels?

## What changed in the measurement

- **Confidence intervals.** Every rate is now `rate [95% CI]`, a cluster
  bootstrap over transcripts (seed set, corpus, human) or bank topics (synth,
  which is one persona). Denominators `n` and cluster counts `k` are printed
  with each table.
- **End-to-end gate scoring.** On the synth split the gate is scored twice:
  with oracle inputs (the authored specificity/ownership labels) and fed by a
  live assessor (`--e2e --assessor <A>`). The gap between the two rows is the
  cost of the assessor's errors to the gate's decisions.
- **Truncation defect and fix.** Claude 5.x models think adaptively, and
  thinking tokens count against `max_tokens`. At `max_tokens=400`, haiku-5-5
  returned empty output, which the previous run (`testbed-2026-10-16T193431`)
  recorded as an error. The adapter now adds effort-scaled thinking headroom,
  raises `TruncatedResponse` / `RefusedResponse` instead of returning an
  unusable reply, and never caches such a reply; the poisoned cache entry was
  deleted. In this rerun haiku-5-5 completed all calls with no errors.
- **Run recorder.** Every bench writes `bench-results/<kind>-<stamp>.{json,md}`
  with provenance (commit, dirty flag, package versions, dataset hashes,
  models and effort) and appends one row to `HISTORY.md`.

## Results

### Assessors — 23 seed turns, k=4 transcripts, effort=low

From `assessors-2026-10-17T004102Z.md` (identical in `testbed-2026-10-17T004200Z.md`).

| assessor | specificity | ownership | both |
|---|---|---|---|
| deterministic | 74% [53–90] | 96% [81–100] | 70% [50–81] |
| llm/haiku-4-5 | 91% [79–100] | 65% [42–92] | 65% [42–92] |
| hybrid/haiku-4-5 | 91% [79–100] | 96% [81–100] | 87% [62–100] |
| llm/haiku-5-5 | 87% [67–96] | 65% [46–90] | 61% [42–80] |
| hybrid/haiku-5-5 | 87% [67–96] | 96% [81–100] | 83% [50–96] |
| llm/sonnet-5 | 87% [75–94] | 83% [69–100] | 70% [61–83] |
| hybrid/sonnet-5 | 87% [75–94] | 96% [81–100] | 83% [67–88] |
| llm/sonnet-5-5 | 96% [81–100] | 78% [53–100] | 74% [50–92] |
| hybrid/sonnet-5-5 | 96% [81–100] | 96% [81–100] | 91% [67–100] |
| llm/opus-5 | 83% [67–88] | 78% [67–96] | 65% [47–80] |
| hybrid/opus-5 | 83% [67–88] | 96% [81–100] | 78% [50–88] |
| llm/opus-5-5 | 91% [75–100] | 78% [53–100] | 70% [50–81] |
| hybrid/opus-5-5 | 91% [75–100] | 96% [81–100] | 87% [67–97] |
| llm/gpt-4.1-mini | 74% [67–79] | 83% [56–94] | 61% [44–69] |
| hybrid/gpt-4.1-mini | 74% [67–79] | 96% [81–100] | 70% [50–78] |
| llm/gpt-4.1 | 78% [50–100] | 87% [75–100] | 65% [25–85] |
| hybrid/gpt-4.1 | 78% [50–100] | 96% [81–100] | 78% [50–100] |

The five Sept 3 models reproduce their baseline point estimates exactly (their
calls are served from the cache). haiku-5-5 is also the only model below 100%
on *within 1* (96% [81–100]).

### End-to-end gate — synth split, n=52, k=4 topics

Oracle-input gate: acc 100% [100–100], premature 0%, stall 0%, minimal pairs
100%. For reference, `budget_only` scores acc 88% [80–97], stall 32% [12–44],
pairs 0%.

| assessor feeding the gate | acc | premature ↓ (n=33) | stall ↓ (n=19) | pairs (n=12, k=3) | assessor agrees on spec / own | file |
|---|---|---|---|---|---|---|
| deterministic | 88% [80–97] | 0% [0–0] | 32% [12–44] | 0% [0–0] | 38% / 92% | `gate-synth-e2e-2026-10-17T004139Z.md` |
| llm/haiku-4-5 | 81% [75–92] | 18% [0–30] | 21% [0–40] | 33% [0–100] | 77% / 23% | `gate-synth-e2e-2026-10-17T004155Z.md` |
| hybrid/haiku-4-5 | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 77% / 92% | `gate-synth-e2e-2026-10-17T004140Z.md` |
| llm/haiku-5-5 | 88% [75–100] | 6% [0–16] | 21% [0–40] | 33% [0–100] | 54% / 62% | `gate-synth-e2e-2026-10-17T004141Z.md` |
| hybrid/haiku-5-5 | 88% [80–97] | 0% [0–0] | 32% [12–44] | 0% [0–0] | 54% / 92% | `gate-synth-e2e-2026-10-17T004142Z.md` |
| hybrid/sonnet-5-5 | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 77% / 92% | `gate-synth-e2e-2026-10-17T004143Z.md` |
| hybrid/opus-5-5 | 92% [86–100] | 0% [0–0] | 21% [0–36] | 17% [0–100] | 85% / 92% | `gate-synth-e2e-2026-10-17T004144Z.md` |

hybrid/haiku-5-5 and deterministic produce the same gate scores as
`budget_only` on every column. The llm/haiku-4-5 run was recorded twice: its
first report file was overwritten by the hybrid/haiku-4-5 run, which started
in the same second (see *Caveats*); `004155Z` is the re-record.

### Testbed — `testbed-2026-10-17T004200Z.md`

- Suites: offline PASS (287 passed), e2e PASS (1), live PASS (5); 293 tests,
  coverage 86%.
- Dataset: corpus 92 (weak labels), synth 52 (spec labels), 12 minimal pairs,
  5 human-adjudicated.
- Gate: synth (oracle) acc 100% [100–100]; corpus acc 77% [73–81], premature
  10% [0–38], stall 50% [0–100]; human acc 80% [57–100], premature 0% [0–0],
  stall 50% [0–100]. On corpus, `always_follow_up` scores 78% [69–85].
- Generation invariants (haiku-4-5 generator, live, cache off, 6 samples):
  exactly one question 100%, ends with the question 100%, grounded 100%, mean
  length 13 words.

## How to read it / caveats

- **Seed set: n=23 items, k=4 transcripts, one labeller, and tuned against.**
  The point estimates are a floor on error, not an unbiased estimate.
- **Synth: k=4 topics, one persona (Maya).** Spec-derived labels measure
  conformance to the written rule, not whether the rule is right.
- **Corpus stall has n=2** (k=2); its interval is [0–100] and carries no
  information.
- **Percentile bootstrap intervals are too narrow at small k.** With 3–4
  clusters, degenerate intervals like `[0–0]` or `[100–100]` mean "no variation
  among the resampled clusters," not certainty.
- **Every assessor ran at effort=low.** This says nothing about how opus-5-5
  or sonnet-5-5 perform at higher depth, and is not a verdict on those models.
- **Recorder stamps have one-second resolution.** Two runs started in the same
  second write the same `<kind>-<stamp>` file; the second overwrites the first,
  while both HISTORY rows survive and point to it. This happened once here
  (`004140Z`).

## Conclusions and next steps

- **No assessor is statistically separable from any other on "both".** The
  highest lower bound among all 17 rows is 67% (hybrid/sonnet-5, hybrid/sonnet-5-5,
  hybrid/opus-5-5) and the lowest upper bound is 69% (llm/gpt-4.1-mini), so
  every pair of intervals overlaps. hybrid/sonnet-5-5 has the highest point
  estimate (91%); hybrid/haiku-4-5 and hybrid/opus-5-5 are at 87%.
- **The hybrid split still holds:** the hybrid has ownership 96% on every
  model, versus 65–87% for the model alone.
- **Sept 3's "specificity scales inversely with capability" does not carry to
  the 5.5 tier:** haiku-5-5 87%, opus-5-5 91%, sonnet-5-5 96%, all with
  overlapping intervals.
- **End to end,** hybrid/haiku-4-5, hybrid/sonnet-5-5 and hybrid/opus-5-5 tie
  at 92% [86–100] accuracy with 0% premature advance; none recovers the
  oracle's 100% on minimal pairs (17%).
- **Cost per assessor call** (mean tokens per cached call × registry price, all
  entries in `cache/`):

  | model | calls | mean in / out tokens | $ per call |
  |---|---|---|---|
  | haiku-5-5 | 33 | 1286 / 129 | $0.00019 |
  | gpt-4.1-mini | 23 | 690 / 59 | $0.00037 |
  | haiku-4-5 | 48 | 962 / 79 | $0.00136 |
  | gpt-4.1 | 23 | 690 / 59 | $0.00185 |
  | sonnet-5-5 | 33 | 1286 / 86 | $0.00343 |
  | sonnet-5 | 23 | 1288 / 100 | $0.00358 |
  | opus-5-5 | 33 | 1286 / 80 | $0.00675 |
  | opus-5 | 23 | 1288 / 139 | $0.00992 |

  haiku-5-5's mean prompt is 34% longer than haiku-4-5's, in line with the
  ~30% token-count difference.
- **Next measurement work:** a held-out label set built from new personas and
  never used for tuning; random-sample human adjudication (not only contested
  items) so the human split estimates accuracy rather than tie-breaking;
  groundedness and recall metrics for the emitted Read.
