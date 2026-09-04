"""Replay every golden transcript through the engine and describe what happens.

Descriptive only: there are no gold ACTION labels yet, so this reports the
distribution of decisions rather than an accuracy. Building the labelled
turn-decision set is the next milestone; until then, treat these as a
regression signal (a distribution that shifts after a change is worth a look),
not a score.
"""

from __future__ import annotations

import json
from collections import Counter

from ..api.contract import Options, TurnRequest
from ..app.turn_engine import TurnEngine
from ..domain import (
    Action, Budget, ConversationState, InterviewPlan, StageSpec, TopicRecord,
    TopicSpec, Turn,
)
from .evaluate import GOLDENS

PLAN = InterviewPlan(
    plan_id="bench",
    stages=[StageSpec(stage_id="s", completion_signal="stage_complete")],
    topics=[TopicSpec(topic_id="t", stage="s")],
    default_budget=Budget(floor=1, ceiling=3),
)


def _path_for(transcript: str):
    """Goldens are not all at the top level - `manipulation/` is a subdirectory."""
    for candidate in GOLDENS.rglob(f"{transcript}.json"):
        return candidate
    raise FileNotFoundError(f"no golden transcript named {transcript!r} under {GOLDENS}")


def replay(transcript: str, engine: TurnEngine | None = None) -> list[dict]:
    engine = engine or TurnEngine()
    data = json.loads(_path_for(transcript).read_text(encoding="utf-8"))

    state = ConversationState(
        topics=[TopicRecord(topic_id="t", stage="s")], current_topic_id="t"
    )
    trace = []
    for i, text in enumerate(data["userTurns"]):
        state.turns.append(Turn(role="user", content=text))
        resp = engine.run(
            TurnRequest(plan=PLAN, state=state, options=Options(generate_text=False))
        )
        trace.append({
            "turn": i,
            "action": resp.decision.action.value,
            "rule": resp.decision.rule_fired,
            "specificity": resp.assessment.specificity.value,
            "ownership": resp.assessment.ownership.value,
        })
        state.topics = resp.state_delta.topics
        if resp.decision.action is Action.ADVANCE:
            # Open a fresh topic so the walk continues rather than stalling.
            state.topics = [TopicRecord(topic_id="t", stage="s")]
        state.turns.append(Turn(role="assistant", content="(next question)"))
    return trace


def run(engine: TurnEngine | None = None) -> dict:
    names = sorted(p.stem for p in GOLDENS.rglob("*.json"))
    per, actions, rules = {}, Counter(), Counter()
    for name in names:
        trace = replay(name, engine)
        per[name] = trace
        actions.update(t["action"] for t in trace)
        rules.update(t["rule"] for t in trace)
    return {
        "transcripts": len(names),
        "turns": sum(len(t) for t in per.values()),
        "actions": dict(actions.most_common()),
        "rules": dict(rules.most_common()),
        "per_transcript": per,
    }


def format_report(result: dict) -> str:
    lines = [f"corpus: {result['transcripts']} transcripts, {result['turns']} turns", "", "  actions:"]
    lines += [f"    {k:<22} {v}" for k, v in result["actions"].items()]
    lines += ["", "  rules fired:"]
    lines += [f"    {k:<28} {v}" for k, v in result["rules"].items()]
    return "\n".join(lines)
