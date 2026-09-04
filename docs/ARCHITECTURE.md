# Component architecture

## What this is

A **standalone conversational-intelligence component**: given the state of an interview, it decides the next move, writes the next message, and emits the closing artifact when the material supports one.

It is built to be ingested by `career-identity-app` eventually, but it does not know that app exists. The integration mechanism is deliberately undecided — MCP, HTTP, or subprocess — so the architecture keeps all of them open and commits to none.

**Decisions taken:** Python core · full turn ownership (decide → generate → emit) · generic engine driven by caller config · **brand voice deferred** — one register for now, revisited as config once the core is proven.

---

## The two hard constraints

**1. Python core, TypeScript consumer.** The target app is Next.js. That closes the in-process import path and makes the seam **process-level** by construction. This is a feature here, not a limitation — it forces a real contract instead of a shared object graph, which is exactly the disconnect that was asked for. Practical consequence: the component must be independently runnable and deployable, and the contract must be the only thing the two repos share.

**2. Stateless.** Every call receives the full state and returns a decision plus a state delta. The consumer remains the system of record. This is what makes MCP, HTTP, and subprocess behave identically — a stateful session would bind the component to one transport and one deployment topology.

---

## Shape: ports and adapters

The domain has **zero imports from adapters**. Everything that touches the network is injected through a Port. That single rule is what makes the component testable without an API key.

```
src/convint/
  domain/          # pure. no I/O, no SDK imports, no async
    state.py       # ConversationState, Turn, TopicRecord, Coverage, Budget
    plan.py        # InterviewPlan  — what to ask about, and the gates
    sufficiency.py # the S/O axes + deterministic feature extraction
    gate.py        # the decision rule — a PURE function
    artifact.py    # artifact schema + readiness predicate
  ports/           # protocols only
    llm.py         # LLMPort
    assessor.py    # SufficiencyAssessor
  adapters/
    llm_anthropic.py  llm_openai.py  llm_fake.py
    assessor_deterministic.py  assessor_llm.py
  app/
    turn_engine.py # orchestration: assess -> decide -> generate -> emit
  api/             # transports, all thin wrappers over turn_engine
    contract.py    # versioned request/response models
    mcp.py  http.py  cli.py
  bench/           # the benchmark, consuming the same public contract
contracts/v1/      # exported JSON Schema — the committed, versioned seam
examples/typescript-client/   # how career-identity-app would call it
```

The transports are each ~100 lines. Adding a fourth seam later is cheap, which is the point.

---

## The seam: a versioned JSON contract

`contracts/v1/` holds exported JSON Schema, committed and versioned. Both repos pin a version; neither imports the other's types.

**Request**

```jsonc
{
  "contract_version": "1.0",
  "plan":  { /* InterviewPlan */ },
  "state": {
    "turns":  [ { "role": "user" | "assistant", "content": "..." } ],
    "topics": [ {
      "topic_id": "childhood.dry_cleaner",
      "stage": "early_life",
      "followups_used": 1,
      "asked_questions": [ "..." ],          // enables redundant-question detection
      "sufficiency": { "specificity": "S2", "ownership": "O0" }
    } ],
    "coverage": { "early_life": true, "career": false },
    "signals":  { "user_signal": "none" }
  },
  "options": { "generate_text": true, "assess": "llm" | "deterministic" }
}
```

**Response**

```jsonc
{
  "contract_version": "1.0",
  "decision": {
    "action": "follow_up" | "advance" | "synthesize" | "refuse_and_continue",
    "sub_action": "deepen" | "redirect" | "reflect_pattern" | "handoff" | "hold",
    "topic_id": "...",
    "rule_fired": "floor_not_met",          // WHY — provenance, not decoration
    "rationale": "..."
  },
  "assessment": { "specificity": "S2", "ownership": "O0",
                  "components": { "scene": false, "stakes": true,
                                  "action": true, "outcome": true } },
  "message":  { "text": "...", "move_type": "ask_for_scene",
                "grounded_on": [ "flashcards" ] } | null,
  "artifact": { /* the Read */ } | null,
  "state_delta": { /* what the caller should persist */ },
  "diagnostics": { "model": "...", "latency_ms": 0, "usage": {}, "assessor": "llm" }
}
```

`rule_fired` is the generalization of the app's `positionInjection` idea: it makes every decision attributable to a named rule, so a bad turn is debuggable as "wrong rule fired" versus "right rule, bad generation." Do not let it be nullable — an unattributable decision is a bug.

---

## Configuration, not hardcoding

**`InterviewPlan`** — supplied by the caller, carries stages, topics, coverage targets, per-topic `floor`/`ceiling` budgets, and each stage's `completion_signal` name. That last field is how the app's `childhood_complete` / `career_reflection_complete` tool names reach the component **without the core knowing they exist**. The app passes its own plan; a different consumer passes a different one.

### Voice: deferred, not designed away

The component generates in **one register** for now. There is no voice config, no profile schema, and no toggle — that complexity buys nothing until the gate itself is proven.

Two cheap things preserve the option to add it later without a rewrite:

- **Generation is a separate step from the decision.** `gate.py` decides; a generator writes the words. Whatever shapes the wording later plugs in at the generation step, and cannot reach back into the decision.
- **`message` is nullable in the contract.** A caller that wants to write its own words today sets `generate_text: false` and renders from `decision` + `assessment`. That is the escape hatch if the single register turns out wrong for the app's brand.

When voice does come back, it should arrive as caller-supplied *data* rather than code in this repo — so the app keeps ownership of its own voice instead of forking the spec across two repos.

## Testability, in tiers

| Tier | What | Network | Speed |
|---|---|---|---|
| 1 | Pure domain unit tests — gate rule, budgets, coverage, sufficiency features | none | ms |
| 2 | Contract tests — JSON Schema validation + golden request/response pairs | none | ms |
| 3 | Replay tests — `llm_fake` backed by recorded responses; full turn engine | none | seconds |
| 4 | Benchmark — real models over the turn-decision dataset, with CIs | yes | on demand, costs money |
| 5 | Consumer contract test — the TypeScript client in `examples/` exercised against a running server | localhost | seconds |

Tests are network-blocked by default: an autouse fixture patches socket connect to raise, so a test that accidentally reaches the API fails loudly instead of quietly costing money. Live tests are marked and deselected.

Tier 5 is the one that proves componentization actually works. A small TS client, kept in this repo and copyable into the app, calling the same server over both MCP and HTTP.

---

## Integration paths kept open

| Path | Command | Notes |
|---|---|---|
| MCP server | `convint mcp` | App registers it as an MCP server; tools map 1:1 to the contract |
| HTTP service | `convint serve` | FastAPI. Vercel supports Python functions, or run it as a sidecar |
| Subprocess | `convint turn --json` | Node `child_process`; crude but zero infrastructure |
| Python library | `from convint import TurnEngine` | For any Python consumer |

All four call the same `turn_engine`. None of them is privileged, and choosing one later requires no core changes.

---

## Model constraints that shape the adapters

- Model IDs are complete as-is and must never be date-suffixed: `claude-opus-5`, `claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5`.
- **Sampling is not tunable on the current Opus/Sonnet models.** Measured live against the API on 2026-09-03:

  | value sent | opus-5 | sonnet-5 | opus-4-8 | haiku-4-5 |
  |---|---|---|---|---|
  | `temperature: 1.0` (the default) | 200 | 200 | 200 | 200 |
  | `temperature: 0.3 / 0.5 / 0.7 / 0.9 / 0.99` | **400** | **400** | **400** | 200 |
  | `temperature: 0` | **400** | **400** | **400** | 200 |
  | `top_p: 0.9` | **400** | **400** | — | 200 |

  Error text: ``` `temperature` is deprecated for this model. ``` So the field is accepted only at its default, where it is a no-op — there is no actual control. Treat sampling as a per-model capability validated at config load, and **omit the field entirely** for these models rather than sending 1.0.

  These models run at temperature 1.0, i.e. the *high-variation* end. What is lost is the ability to make output **more** deterministic, not more natural. Variation in register and phrasing comes from the prompt and from move-type selection, not from a sampling knob.

  **Second, separate constraint at the SDK layer:** `anthropic` 1.x removed `temperature`, `top_p`, and `top_k` from `messages.create()` altogether, for every model. Passing one raises `TypeError` before a request is made. Where sampling is still allowed server-side (Haiku 4.5 only), it must go through `extra_body`. Both facts are pinned by tests, so if a future SDK reinstates the keywords the workaround can be removed deliberately rather than by accident.
- There is **no seed parameter**. Repeatability comes from pinning IDs, fixing the caller's state, and repeating N times — the benchmark reports distributions, never single scores.
- Depth is `output_config.effort` (`low`–`max`), so the system under test is a model *and* an effort tier.

---

## Build order

Steps 1-7 are **complete**: 144 offline tests, 95% coverage, all four seams
agreeing, and a Node consumer driving the running server. Remaining work is the
labelled turn-decision dataset, artifact emission, and a model-backed assessor.

1. `domain/` + `contracts/v1/` + tier-1 and tier-2 tests. **No I/O, no API key, nothing installed beyond pydantic.** The gate rule and the contract are the whole product; everything else is plumbing.
2. `ports/` + `llm_fake` + `assessor_deterministic` → tier-3 replay tests green.
3. `turn_engine` with `generate_text: false` — decision-only end to end.
4. Real LLM adapters, capability validation, cost accounting.
5. Generation — a single register, with `message` nullable so callers can opt out.
6. `api/http.py`, then `api/mcp.py`, then `examples/typescript-client/` → tier 5.
7. `bench/` — the turn-decision dataset and model comparison.
   *(Partially done: assessor-agreement harness and corpus replay exist against a
   23-item seed label set. The labelled turn-decision dataset — the part that
   makes `premature_advance_rate` computable — is the next milestone.)*

Steps 1–3 need no credentials and no spend, and they are where the actual design risk lives.
