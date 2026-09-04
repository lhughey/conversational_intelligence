# convint — conversational-intelligence component

A standalone component that decides how an interview should proceed: whether to
**follow up**, **advance**, or **synthesize**, based on how much usable material
a topic has actually surfaced.

Built to be ingested by a consumer application over an undecided seam (MCP,
HTTP, or subprocess), and fully testable on its own.

## Quick start

```bash
make setup
make test        # 144 tests, no network, no API key, ~1s
make bench       # assessor agreement + corpus replay, offline
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
| `bench/` — assessor agreement, corpus replay | seed set only |
| Labelled turn-decision dataset | **not built** — the next milestone |
| Artifact emission | **not built** |

## Benchmark results, honestly

The deterministic (regex) assessor against 23 hand-labelled turns:

| metric | value |
|---|---|
| specificity exact | 74% |
| specificity within one level | 100% |
| ownership exact | 91% |

Three caveats that matter more than the numbers:

1. **The seed set was used for tuning.** After seeing the first run, the
   signpost rule was added to fix a category of miss. That makes 74% a floor,
   not an unbiased estimate. A held-out set is needed before this number means
   anything comparative.
2. **23 items, one labeller.** Enough to catch a broken assessor, not enough to
   rank two good ones.
3. **The gate rarely fires on merit.** Replaying all 92 corpus turns, `ceiling_reached`
   fires 19 times against `gate_met` 4 times — the regex assessor mostly fails to
   recognise sufficiency, so the ceiling carries the conversation. That is the
   argument for the model-backed assessor, and the reason the port exists.

## Testing

Tests are network-blocked by default: an autouse fixture makes `socket.connect`
raise, so a test that reaches a model API fails loudly instead of quietly costing
money. Costly tests are marked `live` / `e2e` and excluded by `addopts`; a test
asserts that exclusion is still configured.

See `docs/ARCHITECTURE.md` for the design and the remaining build order.
