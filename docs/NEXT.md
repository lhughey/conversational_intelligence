# Where we left off — 2026-10-16

Branch `model-refresh-2026-10` (commit `08ec30e`). Full write-up of the day:
`bench-results/2026-10-16-model-refresh.md`; every run is indexed in
`bench-results/HISTORY.md`.

## State

- Registry has Opus 5.5, Sonnet 5.5, Haiku 5.5, Fable 5.1 (live-probed).
- Current recommended assessor is still `hybrid/haiku-4-5`: no model is
  separable from it at n=23 (all CIs overlap).
- Offline cascade estimate (`bench-results/cascade-offline-*.md`):
  Haiku 5.5 → Sonnet 5.5, escalating only items near the gate's decision
  boundary, matched Sonnet-alone on the synth e2e gate (92%) at 12%
  escalation, ~$0.57 vs $3.42 per 1k items. Directional only (13–23 unique items).
- Held-out set: 65 unlabelled candidates in `data/heldout/` (personas Wren,
  Hollis, Lucian). Never used for tuning — see `data/heldout/README.md`.

## Next, in order

1. **Label the held-out set** (owner: you, ~35–50 min, resumable):
   `make label-heldout` — or `make label-heldout-export`, fill in
   `data/heldout/label-sheet.md`, then `make label-heldout-import`.
2. **Score it** once ≥20 are labelled: `make bench-heldout NOTE="first held-out scoring"`.
   Also compare your labels to the author's intended rungs
   (`data/heldout/intended.jsonl`) — frequent disagreement means the rubric
   needs work before any model comparison.
3. **Wire the cascade analysis to the held-out split** (`scripts/cascade_analysis.py`
   covers only seed + synth today); if Haiku 5.5 → Sonnet 5.5 with the
   boundary trigger holds up, build it as a real `cascade:<cheap>><strong>` assessor.
4. **DSPy**: optimize Haiku 5.5's specificity prompt offline, export it as a
   static prompt for `LLMAssessor`; held-out set is the untouched test split.

## Known gaps

- Read artifact groundedness/recall is not measured as a rate.
- Gate stall of ~21% persists even with a perfect cascade (ownership rules or
  strong-model errors) — separate problem.
- `cost_usd` ignores Haiku 5.5's >100k-token price tier (irrelevant at current prompt sizes).
