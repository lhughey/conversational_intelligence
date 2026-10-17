# Data shape and storage

## The question: do we need a better storage mechanism for the questions?

Yes — but the problem was never the file format. It was that **questions and
answers were stored transcript-shaped when the work needs them bank-shaped.**

A transcript is a recording of one path. That shape has three hard limits, and
all three showed up as measurement failures:

| Limit | How it surfaced |
|---|---|
| The path is fixed, so you cannot construct a case where *advancing* is correct | 72 of 92 labels came out `follow_up`; the must-advance denominator was **2 items** |
| You cannot hold everything constant and vary one thing | No way to tell whether a policy advances on Maya because she is *sufficient* or merely *verbose* |
| It cannot answer a question it was not written for | Unusable for an adaptive interviewer, which is the actual product |

So `always_follow_up` "beat" the gate on that data. That was never a real
result — it was the corpus shape talking.

## The fix: store banks, generate transcripts

An **answer bank** stores a persona's material as *rungs* on a topic — S1, S2,
S3, O2 — served one per question asked.

```jsonc
{ "topic_id": "childhood.dry_cleaner", "stage": "early_life",
  "intents": ["ask_childhood", "ask_early_memory"],
  "rungs": [
    { "rung": "S1", "specificity": "S1", "ownership": "O0", "text": "I helped at my parents' shop…" },
    { "rung": "S2", "specificity": "S2", "ownership": "O0", "requires_prior": ["S1"], "text": "…dry cleaner in Queens…" },
    { "rung": "S3", "specificity": "S3", "ownership": "O0", "requires_prior": ["S2"], "text": "…one woman, furious about a dress…" },
    { "rung": "O2", "specificity": "S1", "ownership": "O2", "requires_prior": ["S3"], "text": "I think I've always been able to see…" } ] }
```

Four things follow that a transcript cannot give:

1. **Gold sufficiency becomes definitional.** A rung authored as an episode *is*
   an episode. The weak-label problem disappears on that axis entirely — no
   inference, no adjudication needed.
2. **Minimal pairs fall out mechanically.** Same topic, same budget, swap only
   the final rung. When the correct action changes there is exactly one reason
   why. 12 such pairs exist today.
3. **Must-advance cases exist by construction.** Serve a rich rung once the
   floor is met and moving on becomes correct. The stall denominator went from
   **2 → 19**.
4. **`requires_prior` makes the antecedent bug a schema invariant.** The
   original `questions.json` served the dress episode with no dry cleaner
   established, so "my mom" and "the stain" dangled. That can no longer be
   authored.

Rungs also **withhold**: a topic serves S1 before S2 before S3. Handing over the
episode on the first ask would make "draw it out — do not hand it over"
unmeasurable, which is the behaviour under test.

## What the minimal pairs bought immediately

| policy | accuracy | minimal pairs |
|---|---|---|
| gate | 100% | **100%** |
| budget_only | **88%** | **0%** |
| length_threshold | 56% | 33% |

`budget_only` — follow up until the ceiling, then move on, ignoring content
entirely — scores a respectable-looking 88% and **0% on minimal pairs**. It is
blind to sufficiency and accuracy alone hides that completely. This is the turn-
counter behaviour the whole component exists to replace, and the pair metric is
what exposes it.

## Storage mechanism: files in git, split by role

Not a database. Reviewable diffs are the entire governance mechanism for
hand-authored data — a label change must show up in a pull request. SQLite makes
that opaque and makes merge conflicts unresolvable. At this scale (hundreds of
items) the cost of files is zero.

But split by **provenance**, because mixing them hides what a number means:

| Path | Kind | Edited by | Format |
|---|---|---|---|
| `data/personas/*.persona.json` | **authored** | humans | JSON, one file per persona |
| `data/turn_decisions/synth_*.jsonl` | **generated** | `convint dataset build` | JSONL, committed |
| `data/turn_decisions/items.jsonl` | **generated** from the corpus | build | JSONL, committed |
| `data/labels/*.seed.jsonl` | **authored** labels | humans | JSONL |
| `data/turn_decisions/human_labels.jsonl` | **adjudicated** | `convint label` | JSONL, append-only |

Generated files are committed so a consumer can read them without running
anything, and a test asserts a fresh build reproduces them — otherwise the
committed copy is a fiction.

## Label provenance is tracked, and it decides what a number means

Every label carries `source`:

- **`spec`** — derived from the written decision rule. Measures **conformance
  and coverage**. The gate scoring 100% on this split is expected and proves
  nothing about whether the rule is *right*.
- **`weak`** — inferred from each transcript's own next user turn. Realistic,
  but the author's assumption rather than ground truth.
- **`human`** — adjudicated. **The only validity evidence.**

The reports print this provenance above every table, so a number cannot be read
without it.

## Getting to validity cheaply

Human judgement is the only thing that shows the *rule itself* is right, so
`convint label` is built to minimise how much of it is needed:

```bash
convint label --split corpus --disagreements-only
```

Items are ordered by information rather than file order — the cases where the
spec label and the live gate disagree come first, because those are the only
ones where an opinion changes anything. There are currently **8 such items out
of 92**. That is a twenty-minute task, not an afternoon.

Adjudications append to their own file and never overwrite generated labels, so
the set can be rebuilt without losing human work.

## Held-out sufficiency set: scored, never tuned against

`data/heldout/` holds 65 unlabelled candidate answers from three new synthetic
personas:

- a thin responder (Wren)
- a tries-to-rush persona (Hollis)
- a verbose-but-abstract persona (Lucian)

The candidates are spread across S0–S3 and O0–O2 on purpose. They include
boundary cases and 10 minimal pairs. **The user labels them**
(`make label-heldout`, or the `-export`/`-import` sheet). The author's
intended rung is kept apart in `intended.jsonl`, and the labelling flow never
reads it. It is used only afterwards, to measure author/labeller agreement.
`make bench-heldout` scores assessors on the labelled items only. It
clusters by persona and refuses below 20 labels.

| Path | Kind | Edited by | Format |
|---|---|---|---|
| `data/heldout/items.jsonl` | **authored** candidates | author, append-only | JSONL |
| `data/heldout/labels.jsonl` | **human** labels | the user, via `make label-heldout*` | JSONL, append-only |
| `data/heldout/intended.jsonl` | author's intended rung | author; agreement analysis only | JSONL |

**The rule: never used for tuning.** That covers prompt edits, few-shot
examples, optimizer (DSPy) train/dev data, and changing anything after
reading its misses. It is the test split and nothing else.
`tests/test_heldout_leak.py` enforces both directions. No held-out text may
appear in the seed labels, the goldens, `data/turn_decisions/`, the synth
banks or `src/`, and only the evaluation code on its `READERS` list may read
the set. The details are in `data/heldout/README.md`.

## Still open

- **The seed sufficiency set was tuned against.** Two fixes were made after
  seeing results, so 74%/96% is a floor, not an unbiased estimate. The
  held-out set above is the fix. Until the user has labelled at least 20
  items, there is no held-out number.
- **One persona.** Maya only. `thin-responder` and `tries-to-rush` banks would
  extend coverage to the low-signal and impatient ends.
- **Effective n ≈ 11**, not 92 — the transcripts are correlated and
  single-authored. Cluster-bootstrap intervals at the transcript level are the
  right treatment; differences under ~10pp should not be read as real.
