# convint — conversational-intelligence component

A standalone component that decides how an interview should proceed: whether to
**follow up**, **advance**, or **synthesize**, based on how much usable material
a topic has actually surfaced.

Built to be ingested by a consumer application over an undecided seam (MCP,
HTTP, or subprocess), and fully testable on its own.

## Quick start

```bash
make setup
make test             # 194 tests, no network, no API key, ~1s
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
| Held-out set never used for tuning | **not built** |

## Benchmark results, honestly

Full detail in `bench-results/`. Two headline findings:

**The hybrid assessor beats every model alone**, on all five models tested.
Specificity goes to the model, ownership to the rules:

| assessor | specificity | ownership | both |
|---|---|---|---|
| deterministic | 74% | **96%** | 70% |
| llm / haiku-4-5 | **91%** | 65% | 65% |
| **hybrid / haiku-4-5** | **91%** | **96%** | **87%** |
| hybrid / opus-5 | 83% | 96% | 78% |
| hybrid / gpt-4.1 | 78% | 96% | 78% |

**Specificity scales inversely with model capability** — haiku 91% > sonnet 87%
> opus 83%, monotonic across three tiers. Stronger models interpret more
generously and inflate S2 into S3, where the rubric asks for conservatism. So
the recommended configuration is `hybrid/haiku-4-5`: 5× cheaper than Opus and
more accurate on this task. Not the expected result, which is why it was worth
measuring.

**The gate evaluation is not yet conclusive**, and says so: `always_follow_up`
beats the gate on strict accuracy (78% vs 60%) because 72 of 92 labels are
`follow_up` — every golden transcript was written to punish premature advance
and none to punish stalling. The metric pair still does its job (that policy
scores 0% premature advance and 100% stall), but the corpus needs fixtures
where advancing is correct before it can rank real policies.

Caveats bounding all of it: 23 sufficiency labels and 92 **weak** gate labels,
one labeller, tuned against the same set, no confidence intervals, and an
effective n nearer 11 than 92 given correlated transcripts. Directional only.

## Testing

Tests are network-blocked by default: an autouse fixture makes `socket.connect`
raise, so a test that reaches a model API fails loudly instead of quietly costing
money. Costly tests are marked `live` / `e2e` and excluded by `addopts`; a test
asserts that exclusion is still configured.

See `docs/ARCHITECTURE.md` for the design and the remaining build order.
