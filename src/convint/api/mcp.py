"""MCP transport.

Split so the dispatch logic is testable without an MCP client: `TOOLS` and
`handle_tool_call` are plain data and a plain function; `serve()` is the only
part that touches the MCP SDK.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from .contract import CONTRACT_VERSION, TurnRequest, TurnResponse

TOOL_DECIDE_TURN = "decide_turn"
TOOL_GET_CONTRACT = "get_contract"


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": TOOL_DECIDE_TURN,
            "description": (
                "Decide how an interview should proceed: follow up, advance, or "
                "synthesize. Takes the full conversation state and an interview plan; "
                "returns the decision, the sufficiency assessment, the state to "
                "persist, and - when the server has a model configured - the next "
                "question to ask (`message`) and, on a supported synthesize, the "
                "Read (`artifact`). Set options.generate_text=false to write the "
                "words yourself. Stateless - pass the whole state every call."
            ),
            "inputSchema": TurnRequest.model_json_schema(),
        },
        {
            "name": TOOL_GET_CONTRACT,
            "description": "Return the versioned JSON Schema this server speaks.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


TOOLS = tool_definitions()

#: Built once per server process on first use (or by `serve`), never per call.
_engine = None


def default_engine():
    global _engine
    if _engine is None:
        from ..app.engine_factory import build_engine

        _engine = build_engine()
    return _engine


def handle_tool_call(name: str, arguments: dict[str, Any], engine=None) -> dict[str, Any]:
    """Pure dispatch. Raises ValueError on an unknown tool."""
    if name == TOOL_GET_CONTRACT:
        return {
            "contract_version": CONTRACT_VERSION,
            "request": TurnRequest.model_json_schema(),
            "response": TurnResponse.model_json_schema(),
        }

    if name == TOOL_DECIDE_TURN:
        engine = engine or default_engine()
        return engine.run(TurnRequest.model_validate(arguments)).model_dump(mode="json")

    raise ValueError(f"unknown tool {name!r}; known: {[t['name'] for t in TOOLS]}")


async def call_tool_async(name: str, arguments: dict[str, Any], engine=None) -> dict[str, Any]:
    """`handle_tool_call` on a worker thread.

    The engine is synchronous and a turn can wait seconds on a model. Run on
    the event loop, one call would stall every other in-flight request on the
    connection; on a thread, overlapping calls proceed together (JSON-RPC ids
    already let the client match out-of-order replies). The engine is shared
    across threads the same way the HTTP server shares it."""
    import anyio

    return await anyio.to_thread.run_sync(partial(handle_tool_call, name, arguments, engine))


def build_server(engine=None):
    """The MCP server (MCP Python SDK 2.x handler API), without a transport."""
    import json

    import mcp.types as types
    from mcp.server import Server

    engine = engine or default_engine()  # built once, before calls can race

    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool.model_validate(t) for t in TOOLS])

    async def call_tool(ctx, params) -> types.CallToolResult:
        try:
            result = await call_tool_async(params.name, params.arguments or {}, engine)
        except ValueError as exc:  # unknown tool or an invalid request (pydantic)
            return types.CallToolResult(content=[types.TextContent(text=str(exc))],
                                        is_error=True)
        return types.CallToolResult(content=[types.TextContent(text=json.dumps(result))])

    return Server("convint", version=CONTRACT_VERSION,
                  on_list_tools=list_tools, on_call_tool=call_tool)


def serve(engine=None, *, assessor: str | None = None,
          model: str | None = None) -> None:  # pragma: no cover - needs a stdio client
    import anyio
    from mcp.server.stdio import stdio_server

    from ..app.engine_factory import build_engine

    global _engine
    _engine = engine or build_engine(assessor=assessor, model=model)
    server = build_server(_engine)

    async def _run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(_run)
