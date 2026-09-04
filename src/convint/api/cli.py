"""CLI transport - the zero-infrastructure seam.

    echo '<TurnRequest json>' | convint turn
    convint serve --port 8000
    convint mcp
    convint contract
"""

from __future__ import annotations

import argparse
import json
import sys

from .contract import CONTRACT_VERSION, TurnRequest, TurnResponse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="convint")
    sub = parser.add_subparsers(dest="command", required=True)

    p_turn = sub.add_parser("turn", help="decide one turn from JSON on stdin")
    p_turn.add_argument("--file", help="read the request from a file instead of stdin")

    p_serve = sub.add_parser("serve", help="run the HTTP server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("mcp", help="run the MCP server on stdio")

    p_bench = sub.add_parser("bench", help="assessor agreement + corpus replay")
    p_bench.add_argument("--json", action="store_true", help="machine-readable output")
    sub.add_parser("contract", help="print the JSON Schema this build speaks")

    args = parser.parse_args(argv)

    if args.command == "contract":
        print(json.dumps({
            "contract_version": CONTRACT_VERSION,
            "request": TurnRequest.model_json_schema(),
            "response": TurnResponse.model_json_schema(),
        }, indent=2))
        return 0

    if args.command == "bench":
        from ..adapters.assessor_deterministic import DeterministicAssessor
        from ..bench import corpus
        from ..bench.evaluate import evaluate, format_report

        agreement = evaluate(DeterministicAssessor())
        replay = corpus.run()
        if args.json:
            print(json.dumps({"agreement": agreement, "corpus": replay}, indent=2))
        else:
            print(format_report(agreement))
            print()
            print(corpus.format_report(replay))
        return 0

    if args.command == "turn":
        from ..app.turn_engine import TurnEngine

        raw = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
        response: TurnResponse = TurnEngine().run(TurnRequest.model_validate_json(raw))
        print(response.model_dump_json(indent=2))
        return 0

    if args.command == "serve":  # pragma: no cover
        from .http import serve

        serve(args.host, args.port)
        return 0

    if args.command == "mcp":  # pragma: no cover
        from .mcp import serve

        serve()
        return 0

    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
