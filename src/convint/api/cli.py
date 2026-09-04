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
    p_bench.add_argument("--gate", action="store_true",
                         help="evaluate the gate against the turn-decision labels")
    p_bench.add_argument("--split", default="synth", choices=["synth", "corpus"],
                         help="synth = balanced with minimal pairs; corpus = realistic but skewed")

    p_ds = sub.add_parser("dataset", help="turn-decision dataset")
    p_ds.add_argument("dataset_command", choices=["build", "stats"])

    p_lab = sub.add_parser("label", help="adjudicate labels (the only path to validity)")
    p_lab.add_argument("--split", default="synth", choices=["synth", "corpus"])
    p_lab.add_argument("--limit", type=int, default=10)
    p_lab.add_argument("--disagreements-only", action="store_true",
                       help="only show items where the spec label and the gate disagree")
    sub.add_parser("contract", help="print the JSON Schema this build speaks")
    sub.add_parser("doctor", help="check credentials resolve from this repo's .env")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        from ..config import status

        st = status()
        print(json.dumps(st, indent=2))
        missing = [k for k in ("anthropic", "openai") if not st[k]]
        if missing:
            print(f"\nmissing: {', '.join(missing)} — add to {st['env_file']}")
            return 1
        return 0

    if args.command == "contract":
        print(json.dumps({
            "contract_version": CONTRACT_VERSION,
            "request": TurnRequest.model_json_schema(),
            "response": TurnResponse.model_json_schema(),
        }, indent=2))
        return 0

    if args.command == "label":
        from ..dataset.adjudicate import run_session

        return run_session(args.split, args.limit, args.disagreements_only)

    if args.command == "dataset":
        from ..dataset.build import build, load, write

        if args.dataset_command == "build":
            from ..dataset.build import build_all

            for split, (items, labels) in build_all().items():
                prefix = "" if split == "corpus" else f"{split}_"
                ip, lp = write(items, labels, prefix)
                print(f"{split}: {len(items)} items -> {ip.name}, {lp.name}")
            return 0

        items, labels = load()
        from collections import Counter

        print(json.dumps({
            "items": len(items),
            "actions": dict(Counter(l.action.value for l in labels)),
            "signals": dict(Counter(i.signal.value for i in items)),
            "label_sources": dict(Counter(l.source for l in labels)),
        }, indent=2))
        return 0

    if args.command == "bench":
        if args.gate:
            from ..bench.gate_eval import format_report as gate_report
            from ..bench.gate_eval import run as gate_run

            result = gate_run(args.split)
            print(json.dumps(result, indent=2) if args.json
                  else gate_report(result, args.split))
            return 0

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
