"""MCP transport.

Split so the dispatch logic is testable without an MCP client: `TOOLS` and
`handle_tool_call` are plain data and a plain function; `serve()` is the only
part that touches the MCP SDK.
"""

from __future__ import annotations

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
                "returns the decision, the sufficiency assessment, and the state to "
                "persist. Stateless - pass the whole state every call."
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


def handle_tool_call(name: str, arguments: dict[str, Any], engine=None) -> dict[str, Any]:
    """Pure dispatch. Raises ValueError on an unknown tool."""
    if name == TOOL_GET_CONTRACT:
        return {
            "contract_version": CONTRACT_VERSION,
            "request": TurnRequest.model_json_schema(),
            "response": TurnResponse.model_json_schema(),
        }

    if name == TOOL_DECIDE_TURN:
        from ..app.turn_engine import TurnEngine

        engine = engine or TurnEngine()
        return engine.run(TurnRequest.model_validate(arguments)).model_dump(mode="json")

    raise ValueError(f"unknown tool {name!r}; known: {[t['name'] for t in TOOLS]}")


def serve() -> None:  # pragma: no cover - requires an MCP client to exercise
    import asyncio

    import mcp.types as types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    server = Server("convint")

    @server.list_tools()
    async def _list() -> list[types.Tool]:
        return [types.Tool(**t) for t in TOOLS]

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> list[types.TextContent]:
        import json

        result = handle_tool_call(name, arguments)
        return [types.TextContent(type="text", text=json.dumps(result))]

    async def _run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())
