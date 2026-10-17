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


def serve(engine=None, *, assessor: str | None = None,
          model: str | None = None) -> None:  # pragma: no cover - needs an MCP client
    import asyncio

    from ..app.engine_factory import build_engine

    global _engine
    _engine = engine or build_engine(assessor=assessor, model=model)

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
