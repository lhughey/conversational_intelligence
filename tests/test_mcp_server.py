"""The MCP server itself (SDK 2.x), driven in-process by a real MCP client.

`serve()` was excluded from coverage, which hid that it no longer started on
the 2.x SDK. These tests build the same server `serve()` runs and talk to it
over the SDK's in-memory transport - no subprocess, no network, no model.
"""

from __future__ import annotations

import json
import time

import pytest

pytest.importorskip("mcp")

import anyio  # noqa: E402
from mcp.client import Client  # noqa: E402

from convint.api.contract import TurnRequest  # noqa: E402
from convint.api.mcp import (  # noqa: E402
    TOOL_DECIDE_TURN, TOOL_GET_CONTRACT, build_server, handle_tool_call,
)
from convint.app.turn_engine import TurnEngine  # noqa: E402
from convint.domain import (  # noqa: E402
    ConversationState, InterviewPlan, StageSpec, TopicRecord, TopicSpec, Turn,
)

REQUEST = TurnRequest(
    plan=InterviewPlan(plan_id="p", stages=[StageSpec(stage_id="s")],
                       topics=[TopicSpec(topic_id="t", stage="s")]),
    state=ConversationState(
        turns=[Turn(role="assistant", content="What were you like as a kid?"),
               Turn(role="user", content="I helped at my parents' dry cleaner.")],
        topics=[TopicRecord(topic_id="t", stage="s")], current_topic_id="t"),
).model_dump(mode="json")


def _with_client(engine, body):
    async def main():
        async with Client(build_server(engine)) as client:
            return await body(client)
    return anyio.run(main)


def test_server_lists_both_tools():
    tools = _with_client(TurnEngine(), lambda c: c.list_tools())
    assert sorted(t.name for t in tools.tools) == [TOOL_DECIDE_TURN, TOOL_GET_CONTRACT]


def test_decide_turn_over_mcp_matches_direct_dispatch():
    engine = TurnEngine()
    result = _with_client(engine, lambda c: c.call_tool(TOOL_DECIDE_TURN, REQUEST))
    assert not result.is_error
    over_mcp = json.loads(result.content[0].text)
    assert over_mcp["decision"] == handle_tool_call(TOOL_DECIDE_TURN, REQUEST, engine)["decision"]


@pytest.mark.parametrize("name, arguments", [
    ("no_such_tool", {}),
    (TOOL_DECIDE_TURN, {"plan": "not a plan"}),
])
def test_bad_calls_are_tool_errors_not_crashes(name, arguments):
    result = _with_client(TurnEngine(), lambda c: c.call_tool(name, arguments))
    assert result.is_error


class _SlowEngine(TurnEngine):
    """Blocks like a synchronous model SDK call does."""

    LATENCY = 0.3

    def run(self, request):
        time.sleep(self.LATENCY)
        return super().run(request)


def test_overlapping_calls_run_concurrently():
    """Regression guard: run on the event loop, N calls take N x latency
    however they are issued. Measured 2026-10-17: 8 calls at 0.5 s took 4.05 s
    overlapping before the fix, 0.51 s after."""
    n = 6

    async def body(client):
        started = time.perf_counter()
        async with anyio.create_task_group() as tg:
            for _ in range(n):
                tg.start_soon(client.call_tool, TOOL_DECIDE_TURN, REQUEST)
        return time.perf_counter() - started

    elapsed = _with_client(_SlowEngine(), body)
    # Serial would be n * LATENCY = 1.8 s; concurrent is ~one LATENCY.
    assert elapsed < 3 * _SlowEngine.LATENCY, f"{n} overlapping calls took {elapsed:.2f}s"
