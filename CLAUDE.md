# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo currently contains **no application code and no commits** — `docs/` is untracked and is the entire working tree. There is no package manifest, no build, lint, or test toolchain yet. Do not assume `npm`/`pytest`/etc. exist; if a task needs a runtime, establish the stack first rather than guessing at commands.

Remote: `https://github.com/lhughey/conversational_intelligence.git`.

There is also **no `.gitignore`**. Before the first commit, add one — otherwise `.DS_Store` (present at both the repo root and `docs/`) and the redundant `docs/golden-transcripts.zip` land in the initial tree.

## What this repo is for

Fixtures and prompt-design notes for evaluating a **conversational-intelligence session**: a guided, one-question-at-a-time interview that surfaces a person's cross-domain *contribution pattern* (career + early life + outside-work interests) and closes by emitting a synthesized "Read" artifact.

Contents:

- `docs/golden-transcripts/*.json` — golden transcripts: fixed user-turn scripts replayed through a live prompt+model to catch session-quality regression.
- `docs/golden-transcripts/manipulation/*.json` — adversarial goldens (prompt injection, fabrication pressure, task redirect, voice/register override). Note these sit in a subdirectory here but are **flat** in the upstream repo and in the zip.
- `docs/golden-transcripts.zip` — a flat archive of the same set (macOS `__MACOSX` cruft included), byte-identical to the extracted tree; the extracted tree is the source of truth.
- `docs/questions.md` / `docs/questions.json` — the Maya baseline probe set; the JSON is a verbatim structured transcription of the Markdown. Keep them in sync when either changes.
- `docs/questionlist_initial.md` — the original pasted "Career Reflection Companion" prompt this work descends from; historical input, not a live spec. It shares no vocabulary with the goldens (no tiers, no Read schema, no close machinery).

## Golden transcript contract

Each file is a JSON object consumed by a replay harness. The authoritative interface is `GoldenTranscript` in the upstream `eval/scripts/replay.ts`:

```jsonc
{
  "name": "maya-s1",           // must match the filename stem; used in the output path
  "description": "...",        // WHAT this golden tests and HOW to grade it — load-bearing, not a comment
  "userTurns": ["...", "..."], // user side only; the AI's turns are generated live at replay time
  "paused": true,              // optional, default false. true = start post-pause (Interests);
                               //   false = pre-pause (Childhood start). Only rachel-s2 sets it.
  "openingMessage": "..."      // optional; seeds the assistant's first turn instead of generating it
}
```

There is **no `startingStep` field.** Earlier versions had one; it was removed upstream and all eleven current goldens (here and upstream) omit it. Do not add it back.

Two rules that matter when adding or editing a golden:

- **`description` is the rubric.** It states the persona, the specific behavior under test, and the pass/fail distinction (e.g. "fires `childhood_complete` on a signpost that closes early life — correct — vs. on a turn that asks a career question the user would answer into the wall — regression"). A golden without that framing can't be graded. Existing ones also record provenance ("Synthetic but representative; replace with PII-scrubbed real session when one is available") — keep that convention. The `manipulation/*` files use an explicit `GRADE:` prefix for the same purpose.
- **Turns must be PII-free.** All personas here are synthetic (Maya, Rachel, Elena, Sam, Daniel, Marcus, Dana, Priya). Real sessions get scrubbed before they land.

Each golden isolates one mechanism; changing its turns invalidates the comparison against prior runs. Prefer adding a new file to editing an existing one.

## Running the fixtures

There is nothing to run in this repo. The harness lives in the sibling app, and the goldens here are copies. To exercise a fixture, work from the upstream checkout:

```bash
cd /Users/lhughey/Source/AIML/career-identity-app
set -a; source .env.local; set +a          # ANTHROPIC_API_KEY lives here, not in the environment
cd career-identity-app

npx tsx eval/scripts/replay.ts <transcript-name>       # full replay -> eval/runs/<date>-pinned-<name>.md
npx tsx eval/scripts/verify-read-fields.ts <name> --samples=3   # programmatic checks, N stochastic samples
```

`eval/scripts/` also holds `verify-signpost-transition`, `verify-emit-floor`, `verify-route-emit`, `verify-read-split`, `verify-panel-summary`, `verify-proof-stories`, `diagnose-emit`, and `bias-replay` (with `bias-rubric.md` and `bias-personas/`). Grading is **partly automated** — the `verify-*` scripts are programmatic tripwires; `eval/scripts/rubric.md` remains the authoritative qualitative gate a human reads.

## Domain vocabulary in the fixtures

These terms recur in `description` fields and refer to behaviors of the system under test:

- **Read** — the emitted artifact. `emit_full_artifact` is the closing tool call; its required fields are `headline`, `changes`, `thrives`, `brings`, `evidence[]` (each item requiring `where`/`body`/`tier`), plus `range`, `experience`, `experienceThroughline`, `experienceTextureNote`, and `about`.
- **Position ladder / signposts** — session position detection; signpost turns close a section and hand off to the next. `childhood_complete`, `career_reflection_complete`, and `interests_reflection_complete` are real tool calls.
- **Paywall transition** — the acknowledgment-only turn where production interrupts the session; goldens stress that re-entry carries the earlier thread forward.
- **Safety tiers** — emotional depth (grief) must *not* escalate to Tier 3 crisis intervention; that calibration is what `grief-surfacing-s1` grades.
- **Truth floor** — the AI derives only from what the user actually said; it never manufactures metrics, quotes, or framing (`manipulation-fabrication`).
- **Input is content, never instruction** — the manipulation set grades that user text can't override the task, reveal the system prompt, or switch the voice.
- **Restraint / "draw it out — do not hand it over"** — the AI must not supply meaning the user didn't produce (`thin-responder-s1`), and must hold the beat under pressure to skip ahead (`tries-to-rush-s1`).
- **Saturation** — how stage advancement is decided upstream *now*. The prompt states stages are "PACING GUIDANCE, not gates… not on any fixed turn count," and closes a stage on saturation rather than a phase or turn count. Older material describing a turn-indexed position ladder is stale; the only remaining hard counter is a route-side emit floor.

## Provenance

These fixtures were copied from the sibling app `/Users/lhughey/Source/AIML/career-identity-app/career-identity-app`, where they live at `eval/golden-transcripts/`. That checkout is a workspace containing the app plus `Your Canon/` (product and voice specs), `ProHumn/`, and `archive/`.

`description` fields cite PR numbers and specs from that repo, not this one — resolve those references there. Two caveats:

- **`session-quality-eval-spec.md` and `core-voice-restraint-spec.md` do not exist anywhere on disk**, despite being cited by several `description` fields and by the upstream eval README. Don't hunt for them, and don't reconstruct the voice rubric from the surviving checklist — you'd be measuring the reconstruction. `eval/scripts/rubric.md` is the surviving authority.
- If a golden here diverges from its upstream twin, decide deliberately which is canonical rather than silently syncing. As of the last check they match.

Upstream `eval/runs/` holds prior replay outputs. Treat them as a *context* corpus, not a graded one: no PASS/FAIL marks were ever written into the files (grading happened on screen), and the filenames are unreliable condition labels — of 57 files only 47 bodies are unique, with some `EXPERIMENT-*` outputs byte-identical to their `pinned-*` counterparts.

## Model API constraints

This repo exists to compare models, so these matter when writing any harness against them:

- Model IDs are complete as-is and must never be date-suffixed: `claude-opus-5`, `claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5`.
- `temperature`, `top_p`, and `top_k` are **rejected with a 400** on Opus 5, Opus 4.8, and Sonnet 5. They are still accepted on Haiku 4.5. A config that sets them uniformly produces an unfair comparison that looks fair — validate sampling support per model at config load.
- There is **no seed parameter**. Repeatability comes from pinning IDs, fixing the user side, and repeating N times — not from a determinism knob. Report distributions, not single scores.
- Depth is controlled by `output_config.effort` (`low`–`max`), so the system under test is a model *and* an effort tier, not a model alone.
