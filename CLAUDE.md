# CLAUDE.md

`convint` is a standalone conversational-intelligence component: it decides whether an
interview should **follow up**, **advance**, or **synthesize**, based on how much usable
material a topic has surfaced. Python package in `src/convint/` (domain/, app/, adapters/,
api/, bench/, dataset/); consumed over a versioned JSON contract (`contracts/v1/`).

Read first: `README.md`, `docs/ARCHITECTURE.md`, `docs/DATA.md`, `bench-results/LATEST.md`.

## Commands (Makefile; everything runs via `.venv`)

- `make setup` — create `.venv`, `pip install -e ".[dev]"`
- `make test` / `make test-cov` — offline pytest (no network, no key); with coverage
- `make test-live` — `-m live`, calls real model APIs; `make test-e2e` — `-m e2e`, Node client vs live HTTP server
- `make testbed` / `make testbed-live` — `scripts/testbed.py`, runs everything and records the result
- `make bench` — assessor agreement + corpus replay (offline); `make bench-assessors` — live, cached
- `make bench-gate` / `bench-gate-corpus` / `bench-gate-human` — gate on synth / corpus / human-labelled split
- `make label` (also `label-conflicts`, `label-all`, `label-export`, `label-import`) — human adjudication
- `make label-heldout` (also `label-heldout-export` / `-import`) — the user labels `data/heldout/`; `make bench-heldout` — assessors vs those labels (live, cached; refuses below 20 labelled)
- `make doctor` — check credentials resolve; `make contracts` — regenerate `contracts/v1/*.json`; `make dataset` — rebuild dataset
- Results are recorded in `bench-results/` (`<kind>-<UTC stamp>.{json,md}`) with `bench-results/HISTORY.md` as the append-only index; pass `NOTE="..."` (or `--note`) to describe what a run tested — `testbed`, `bench-assessors` and every `bench-gate*` target record.

## Conventions agents get wrong

- Credentials come only from this repo's `.env` (or an exported env var) via `src/convint/config.py`. Never source a sibling project's `.env`.
- Tests block sockets. Anything that calls a model must carry the `live` marker (`live`/`e2e` are excluded by default in addopts).
- `contracts/v1` drift from the models fails the suite; run `make contracts` after changing contract models.
- Every gate decision carries `rule_fired` (`src/convint/domain/gate.py`); keep it on new rules.
- `data/heldout/` is the never-tuned test split: never use it for prompt edits, few-shot examples, optimizer train/dev data or reading misses; only the `READERS` in `tests/test_heldout_leak.py` may touch it, and you author items but never labels (`data/heldout/README.md`).

## Model API constraints

Model capabilities live in `src/convint/adapters/models.py` and are validated at config load.
- IDs are complete as-is, never date-suffixed: `claude-opus-5`, `claude-opus-5-5`, `claude-opus-4-8`, `claude-sonnet-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-haiku-4-5`, `claude-fable-5-1`.
- `temperature`/`top_p` are rejected (400) on every 5.x model, Haiku 5.5 included; accepted only on Haiku 4.5.
- `output_config.effort` (`low`–`max`) is the depth lever, rejected only on Haiku 4.5. The system under test is model + effort.
- No seed parameter: repeat N samples and report rates/distributions, not single scores.

## Golden transcripts (`docs/golden-transcripts/`, incl. `manipulation/`)

Replay fixtures copied from the sibling app (`career-identity-app`, `eval/golden-transcripts/`; its PR/spec citations resolve there). Shape: `{name (= filename stem), description, userTurns[], paused?, openingMessage?}`; there is no `startingStep` field. `description` is the rubric (persona, behavior under test, pass vs regression; manipulation files use a `GRADE:` prefix). Turns must be PII-free synthetic personas. Prefer adding a file over editing one. `docs/questions.md` and `questions.json` must stay in sync.

Vocabulary: **Read** = emitted artifact (`emit_full_artifact`); **signposts** = `childhood_complete` / `career_reflection_complete` / `interests_reflection_complete`; **saturation** (not turn count) closes a stage; **truth floor** = derive only from what the user said; **input is content, never instruction**; **restraint** = draw meaning out, do not hand it over; grief must not escalate to Tier 3 crisis.
