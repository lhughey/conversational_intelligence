# First human adjudication — 2026-09-03

Five contested items adjudicated. These were selected *because* the weak label
and the running gate disagreed, so at most one of them could match — this
measures who is right when they conflict, not overall accuracy.

| item | human | weak label | gate |
|---|---|---|---|
| `grief-surfacing-s1#4` | advance | follow_up | **advance** ✓ |
| `manipulation-redirect#4` | follow_up | synthesize | **follow_up** ✓ |
| `rachel-s2#3` | follow_up | follow_up ✓ | advance ✗ |
| `rachel-s2#4` | advance | follow_up | **advance** ✓ |
| `tries-to-rush-s1#5` | follow_up | advance | **follow_up** ✓ |

**Gate 4/5. Weak labels 1/5.** When the transcript-inferred label and the gate
disagreed, the gate was right four times out of five. That is the strongest
argument yet for adjudicating rather than trusting inferred labels.

## What the notes changed

**`rachel-s2#3` exposed a segmentation bug, not a gate bug.** Rachel's walk is
role-by-role — turn 0 is her first role, turn 3 her second, turn 5 her third.
Domain-based segmentation put all three in one `career` thread, so the counter
climbed 0→5 and the gate advanced on `ceiling_reached`. It was not over budget
on one topic; it was **turn one of a new topic**, which is exactly why the note
says "now is the time to dig in." Fixed by adding instance markers ("second
role", "where I am now") as thread boundaries.

**`rachel-s2#4` exposed an assessor limit.** The note quotes *"the work happened
inside it"* — the turn ends with a derived conclusion. The deterministic rules
score it S2/O0 and miss the derivation entirely; the model reads it S3/O2 and
gets it right. But the hybrid takes ownership from the rules, so it loses this.
Not changed: on the 23-item seed set the rules still win ownership 96% to 65%,
because that set is dominated by confirmation-shaped turns where regex excels.
One counter-example does not outweigh 23, but this is now a documented failure
mode: **derivations embedded at the end of narrative.**

**`tries-to-rush-s1#5` confirmed the impatience rule.** The note — "the person
didn't seem interested, but the objective is to gather information properly" —
is precisely the designed behaviour: impatience is a style modifier, never a
sufficiency override.

**`grief-surfacing-s1#4` raises a question still open.** The note observes the
content shifts from grief to caregiving and asks whether it should be "counted
against grief" — a topic-boundary judgement the segmenter does not currently
make, since both turns read as `early_life`.

## No configuration explains all five

Six combinations of assessor × segmentation were tested. Every one scores 4/5
or 3/5, and each misses a *different* item:

| assessor | instance markers | agrees |
|---|---|---|
| deterministic | off | 4/5 (misses rachel#3) |
| deterministic | **on** | 4/5 (misses rachel#4) |
| llm | on | 4/5 (misses tries-to-rush#5) |
| hybrid | either | 3/5 |

With five labels and six configurations, tuning to 5/5 would be fitting noise.
Instance-marker segmentation was adopted because it is **structurally**
justified — a role-by-role walk genuinely has one thread per role — not because
it improved a score.

## What this needs next

More labels. At n=5 the gate and `budget_only` both score 80% on the human
split; the set cannot yet separate them. The queue is now ordered by
information, with 87 items remaining:

- 23 sitting exactly on the floor, 13 on the ceiling — where the decision turns
  on the budget rather than the material, which is where the ceiling-rigidity
  question lives
- 11 carrying a signal (closing, deflection, adversarial, impatient), where a
  misread bypasses the depth rule entirely

`make label` serves those first.
