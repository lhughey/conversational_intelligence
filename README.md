# convint — conversational-intelligence component

A standalone component that decides how an interview should proceed: whether to
**follow up**, **advance**, or **synthesize**, based on how much usable material
a topic has actually surfaced.

Built to be ingested by a consumer application over an undecided seam (MCP,
HTTP, or subprocess), and fully testable on its own.

## Quick start

```bash
make setup
make test             # 287 tests, no network, no API key, ~2s
make bench            # assessor agreement + corpus replay, offline
make doctor           # confirm credentials resolve from this repo's .env
make bench-gate       # gate vs the balanced split + dumb baselines, offline
make label            # adjudicate the items where spec and gate disagree
make bench-assessors  # compare assessors across 5 models (live, cached)
make dataset          # rebuild the turn-decision dataset
```

Optional, and they cost or bind ports:

```bash
make test-e2e    # starts the server, drives it with the Node client
make test-live   # hits the real model API
```

## Using it

```bash
convint contract                    # the JSON Schema this build speaks
echo "$REQUEST" | convint turn      # subprocess seam
convint serve --port 8000           # HTTP seam
convint mcp                         # MCP seam (stdio)
```

All four call the same engine and return the same answer; a test asserts that.

Every entry point is full-featured: with a credential in this repo's `.env`, a
turn returns the decision, the next question (`message`) and, on a supported
close, the Read (`artifact`). The **operator** picks the models, never the caller:

```bash
CONVINT_ASSESSOR=hybrid:haiku-4-5   # deterministic | llm:<key> | hybrid:<key> (default shown)
CONVINT_MODEL=haiku-4-5             # question + Read model; `none` = decision only
convint serve --port 8000
# or override per process (also on `convint mcp` / `convint turn`):
convint serve --assessor deterministic --model none   # free, offline
```

Callers choose per turn with `options.assess` (`server` default, `deterministic`
to force the free assessor, `llm` to ask for the model one) and
`options.generate_text`. A missing credential or a failed model call never fails
a turn: it falls back (deterministic assessor, `message`/`artifact` null) and says
why in `diagnostics.warnings`, with `diagnostics.degraded: true`. Usage and
`cost_usd` are reported per turn.

## The decision rule

Sufficiency is scored on two independent axes — **Specificity** (S0–S3, how
concrete the material is) and **Ownership** (O0–O2, who did the meaning-making).
A single scale conflates them, and the corpus contains turns that are confident
and self-describing with no concrete instance behind them.

Advancing requires **both** a satisfied follow-up floor and a passed sufficiency
gate; a ceiling overrides both, because a floor with no ceiling is interrogation.
Three rules are easy to get backwards and are pinned by tests:

- **Topic change outranks sufficiency** — a user volunteering new material is
  following their own energy.
- **Impatience does not override the gate** — pressure is not sufficiency.
  Closing ("that's enough") is agency and is respected; impatience ("hurry up")
  is not.
- **A confirmation or closing turn is a signpost, not material** — it can be
  long and still carry nothing new.

Every decision carries a `rule_fired`. An unattributable decision is a bug, and
a brute-force test over every signal × level × budget combination proves none
occur.

## Where it stands

| Layer | State |
|---|---|
| `domain/` — gate, sufficiency, plan, artifact | done, pure, 98–100% covered |
| `contracts/v1/` — versioned JSON Schema | done; drift fails the suite |
| `ports/` + `adapters/` — Anthropic, OpenAI, fake | done |
| `app/` — turn engine, move selection, generation | done (single register) |
| `api/` — HTTP, MCP, CLI | done |
| `adapters/` — deterministic, **LLM**, and **hybrid** assessors | done |
| `adapters/cache.py` — content-addressed response cache | done |
| `domain/signals.py` — user-intent detection | done |
| `dataset/` — 92 turn-decision items + weak labels | done (labels weak) |
| `bench/` — assessor agreement, gate evaluation, corpus replay | done |
| `app/artifact_builder.py` — Read emission with a truth floor | done |
| `config.py` — credentials from this repo only | done |
| `dataset/bank.py` — persona answer banks | done (Maya) |
| `dataset/synth.py` — balanced set + minimal pairs | done |
| `dataset/adjudicate.py` — human labelling CLI | done |
| Human-adjudicated labels | **8 items queued** — run `make label` |
| Banks for thin-responder / tries-to-rush | **not built** |
| Held-out set never used for tuning | built (65 items); **awaiting your labels** — `make label-heldout` |

## Benchmark results, honestly

Every recorded run is indexed in `bench-results/HISTORY.md`; the latest
summary is `bench-results/2026-10-16-model-refresh.md`. Numbers below are from
`assessors-2026-10-17T004102Z.md` (23 seed turns, k=4 transcripts, assessor at
effort=low; 95% cluster-bootstrap CIs).

**The hybrid assessor beats the model alone on every model tested.**
Specificity goes to the model, ownership to the rules:

| assessor | specificity | ownership | both |
|---|---|---|---|
| deterministic | 74% [53–90] | 96% [81–100] | 70% [50–81] |
| llm / haiku-4-5 | 91% [79–100] | 65% [42–92] | 65% [42–92] |
| hybrid / haiku-4-5 | 91% [79–100] | 96% [81–100] | 87% [62–100] |
| hybrid / haiku-5-5 | 87% [67–96] | 96% [81–100] | 83% [50–96] |
| hybrid / sonnet-5-5 | 96% [81–100] | 96% [81–100] | 91% [67–100] |
| hybrid / opus-5-5 | 91% [75–100] | 96% [81–100] | 87% [67–97] |
| hybrid / gpt-4.1 | 78% [50–100] | 96% [81–100] | 78% [50–100] |

**No assessor is statistically separable from another.** Every pair of "both"
intervals overlaps across all 17 assessor rows. The Sept 3 finding that
specificity falls with model capability (haiku-4-5 91% > sonnet-5 87% > opus-5
83%) does not carry to the 5.5 tier (haiku-5-5 87%, opus-5-5 91%, sonnet-5-5
96%). `hybrid/haiku-4-5` remains a cheap configuration within the noise of the
best; all assessors ran at effort=low, so this is not a verdict on the larger
models at higher depth.

**End to end on synth** (gate fed by a live assessor instead of the authored
labels), hybrid/haiku-4-5, hybrid/sonnet-5-5 and hybrid/opus-5-5 all score
92% [86–100] accuracy with 0% premature advance, against 100% with oracle
inputs.

**The gate evaluation is not yet conclusive**, and says so: `always_follow_up`
matches the gate on strict accuracy (78% [69–85] vs 77% [73–81]) because 72 of 92 labels are
`follow_up` — every golden transcript was written to punish premature advance
and none to punish stalling. The metric pair still does its job (that policy
scores 0% premature advance and 100% stall), but the corpus needs fixtures
where advancing is correct before it can rank real policies.

Caveats bounding all of it: 23 sufficiency labels and 92 **weak** gate labels,
one labeller, tuned against the same set, and only 4–11 clusters behind each
interval (corpus stall rests on n=2), so the percentile intervals are if
anything too narrow. Directional only.

## Testing

Tests are network-blocked by default: an autouse fixture makes `socket.connect`
raise, so a test that reaches a model API fails loudly instead of quietly costing
money. Costly tests are marked `live` / `e2e` and excluded by `addopts`; a test
asserts that exclusion is still configured.

See `docs/ARCHITECTURE.md` for the design and the remaining build order.
