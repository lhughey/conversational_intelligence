# Held-out sufficiency set

An evaluation set for the sufficiency assessor (specificity S0–S3, ownership
O0–O2) that has **never been tuned against**. The 23-item seed set
(`data/labels/sufficiency.seed.jsonl`) has been, so its numbers are a floor.
This set exists so a number can be read as an estimate. It is also the
test split, never to be touched, for any later automated prompt optimization
(DSPy or otherwise).

## Rules

1. **Never use it for tuning.** No prompt edits, few-shot examples, rubric
   tweaks, model or effort choices, or optimizer train/dev splits may be
   drawn from it. Reading its misses and then changing a prompt counts as
   tuning: it spends the set. That is why `make bench-heldout` prints only
   aggregates and no item text.
2. **Only evaluation code reads it.** `tests/test_heldout_leak.py` enforces
   this. Only the files on its `READERS` list may mention the set, and no
   held-out id or text may appear in the seed labels, golden transcripts,
   `data/turn_decisions/`, `data/personas/` (synth banks) or anywhere under
   `src/`. Never add an optimization, few-shot or generation module to
   `READERS`.
3. **The labels are yours.** `labels.jsonl` is written only by the labelling
   flow below. The author's intended rung is in `intended.jsonl`. Don't open
   it, or `personas/`, until you have finished labelling. The labelling flow
   never reads either one.

## Files

| file | what | written by |
|---|---|---|
| `items.jsonl` | `{id, persona, topic, question, text}`: the candidates | author (append only) |
| `labels.jsonl` | `{item_id, specificity, ownership, text_sha, note, source, via, labelled_at}` | you, via `make label-heldout*` |
| `intended.jsonl` | `{id, specificity, ownership, boundary, pair, rationale}`: the author's intended rung | author; read only for author/labeller agreement |
| `personas/*.persona.json` | persona metadata in the bank shape, with **empty rungs** (rungs would carry labels) | author |
| `label-sheet.md` | scratch sheet from `make label-heldout-export` | generated |

The persona files live here, not in `data/personas/`. Synth builds from that
directory, and these texts must never become served or tuned-against
material.

## How to label

```bash
make label-heldout          # interactive; q saves and quits; rerun to resume
# or
make label-heldout-export   # writes data/heldout/label-sheet.md
#   ...fill in the S[...] / O[...] lines...
make label-heldout-import   # appends them to labels.jsonl (safe to re-run)
```

You see the interviewer's question and the person's answer, plus the rubric.
You don't see the persona, the topic or any proposed label. Items come in a
fixed, seeded shuffle, so neither the persona order nor the rung order gives
anything away. Judge the answer only, as if nothing came before it. Type one
digit per axis, or both at once (`2 1` = S2/O1). `-` skips an item and `?`
reprints the rubric. Each label is saved as soon as you give it.

To correct a label, append a new line or edit the existing one. The last line
for an id wins. A label is pinned to the text it judged (`text_sha`), so if
an item's text changes, scoring fails loudly until you re-label it.

65 items take roughly 35–50 minutes at 30–45 seconds each. Scoring needs at
least 20 labels.

## How to score

```bash
make bench-heldout                                          # every assessor (live, cached)
.venv/bin/python -m convint.api.cli bench --assessors --split heldout   # deterministic only, offline
.venv/bin/python -m convint.api.cli bench --assessors --split heldout --assessor hybrid:haiku-4-5,llm:haiku-4-5
```

Only user-labelled items are scored, and the report says `n labelled of N`.
Below 20 labels the command refuses with exit 2: it calls no model and
records nothing. Intervals are a cluster bootstrap over the three personas.
With k=3 they are too narrow, so read them as directional. Runs are recorded
in `bench-results/` and indexed in `HISTORY.md`, the same as every other
benchmark. The report also prints how often your labels agree with the
author's intended rung, overall and on items authored as boundary cases.

## How to add items

- Append to `items.jsonl` with a new opaque id:
  `python -c "import secrets; print('ho-' + secrets.token_hex(3))"`. Add the
  matching line to `intended.jsonl` and the topic to the persona file.
- Write new items from the rubric. Never write them from an assessor's
  failures on this set.
- Never edit or delete a labelled item. Add a new one instead.
- Personas must be synthetic and PII-free. Never use a name the goldens or
  banks already use (Maya, Rachel, Elena, Sam, Daniel, Marcus, Dana, Priya).
- Run `make test`. The leak guard checks the new text against everything that
  has been tuned against.
