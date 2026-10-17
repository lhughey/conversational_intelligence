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
    p_bench.add_argument("--split", default="synth",
                         choices=["synth", "corpus", "human", "heldout"],
                         help="synth = balanced with minimal pairs; corpus = realistic but skewed; "
                              "human = adjudicated items only (the only validity evidence); "
                              "heldout = with --assessors, the never-tuned sufficiency set "
                              "scored against YOUR labels")
    p_bench.add_argument("--assessors", action="store_true",
                         help="with --split heldout: score assessors on the held-out "
                              "sufficiency set (refuses below 20 labelled items)")
    p_bench.add_argument("--e2e", action="store_true",
                         help="with --gate --split synth: add a row where the gate is fed by an "
                              "assessor instead of the authored specificity/ownership")
    p_bench.add_argument("--assessor", default="deterministic",
                         help="assessor for --e2e: deterministic (offline), llm:<key> or "
                              "hybrid:<key> (model registry key; calls the API on a cache miss). "
                              "With --assessors: a comma-separated list of those, or 'all'")
    p_bench.add_argument("--note", default=None,
                         help="with --gate or --assessors: what this run is testing, recorded in "
                              "bench-results/HISTORY.md (else $NOTE, else '(no note)')")

    p_ds = sub.add_parser("dataset", help="turn-decision dataset")
    p_ds.add_argument("dataset_command", choices=["build", "stats"])

    p_lab = sub.add_parser("label", help="adjudicate labels (the only path to validity)")
    p_lab.add_argument("--split", default="synth", choices=["synth", "corpus", "heldout"],
                       help="heldout = label the held-out sufficiency set (S and O per answer)")
    p_lab.add_argument("--limit", type=int, default=10,
                       help="items per session (with --split heldout, 0 = all remaining)")
    p_lab.add_argument("--disagreements-only", action="store_true",
                       help="only show items where the spec label and the gate disagree")
    p_lab.add_argument("--export", action="store_true",
                       help="write an editable review file instead of prompting")
    p_lab.add_argument("--import", dest="do_import", action="store_true",
                       help="read decisions back out of the review file")
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

    if args.command == "label" and args.split == "heldout":
        from ..dataset import label_heldout

        if args.disagreements_only:
            parser.error("--disagreements-only does not apply to --split heldout")
        if args.do_import:
            print(json.dumps(label_heldout.import_sheet(), indent=2))
            return 0
        if args.export:
            path, count = label_heldout.export()
            print(f"wrote {count} unlabelled held-out items -> {path}")
            return 0
        return label_heldout.run_session(args.limit)

    if args.command == "label":
        from ..dataset.review import export, import_decisions

        if args.do_import:
            print(json.dumps(import_decisions(args.split), indent=2))
            return 0
        if args.export:
            path, count = export(args.split)
            print(f"wrote {count} items for review -> {path}")
            return 0

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
        if args.assessors or args.split == "heldout":
            if args.split != "heldout" or not args.assessors or args.gate or args.e2e:
                parser.error("the held-out set is scored with `--assessors --split heldout` "
                             "(no --gate/--e2e); the seed set is `make bench-assessors`")
            return _bench_heldout(args, parser)
        if args.gate:
            from ..bench.gate_eval import format_report as gate_report
            from ..bench.gate_eval import make_assessor
            from ..bench.gate_eval import run as gate_run

            assessor = None
            if args.e2e:
                if args.split != "synth":
                    parser.error("--e2e applies to --split synth only; corpus/human items "
                                 "already carry assessor-derived state")
                try:
                    assessor = make_assessor(args.assessor)
                except (ValueError, KeyError) as exc:
                    parser.error(str(exc))
            from ..bench import record as recorder

            prov = recorder.provenance()
            result = gate_run(args.split, e2e_assessor=assessor)
            report = gate_report(result, args.split)
            print(json.dumps(result, indent=2) if args.json else report)
            models = ["deterministic assessor (offline)"] if args.e2e else []
            if assessor is not None and args.assessor != "deterministic":
                models = [recorder.assessor_model_label(args.assessor.partition(":")[2])
                          + f" via {args.assessor.partition(':')[0]}"]
            paths = recorder.record_run(
                f"gate-{args.split}" + ("-e2e" if args.e2e else ""), args.note,
                {"split": args.split, "e2e_assessor": args.assessor if args.e2e else None,
                 "policies": result},
                "```\n" + report + "\n```\n", models=models,
                headline=recorder.gate_headline(result, args.split), prov=prov,
            )
            print(f"recorded -> {paths['md'].name} (and HISTORY.md)", file=sys.stderr)
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


def _bench_heldout(args, parser) -> int:
    """Score assessors on the held-out set. Refuses - exit 2, no model call,
    nothing recorded - until enough items carry the user's label."""
    from ..bench import heldout
    from ..bench import record as recorder

    try:
        specs = heldout.expand_assessor_specs(args.assessor)
    except ValueError as exc:
        parser.error(str(exc))
    st = heldout.status()
    print(heldout.format_status(st), file=sys.stderr)
    if st["n_labelled"] < heldout.MIN_LABELLED:
        print(f"no headline: {st['n_labelled']} labelled of {st['n_items']}; need >= "
              f"{heldout.MIN_LABELLED}. Label more with `make label-heldout`.",
              file=sys.stderr)
        return 2

    prov = recorder.provenance()
    rows = heldout.run(specs)
    agreement = heldout.author_agreement()
    report = heldout.render(rows, st, agreement)
    payload = {"split": "heldout", "status": st, "assessors": rows,
               "author_agreement": agreement}
    print(json.dumps(payload, indent=2) if args.json else report)
    keys = heldout.model_keys(specs)
    models = [recorder.assessor_model_label(k) for k in keys] or ["deterministic (offline)"]
    paths = recorder.record_run("assessors-heldout", args.note, payload, report,
                                models=models, headline=heldout.headline(rows, st), prov=prov)
    print(f"recorded -> {paths['md'].name} (and HISTORY.md)", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
