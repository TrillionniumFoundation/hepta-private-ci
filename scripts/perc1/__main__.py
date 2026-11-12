"""Run with PYTHONPATH=scripts python -m perc1 ..."""

import argparse
import json
import sys
from pathlib import Path

from .schema import Dataset, Invalid, load


def main():
    parser = argparse.ArgumentParser(
        description="PERC-1 audit harness: structural PASS never grants scientific qualification."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    cmd = commands.add_parser("smoke")
    cmd.add_argument("--output", required=True)
    cmd = commands.add_parser("report")
    for name in ("manifest", "dataset", "traces", "evaluator"):
        cmd.add_argument(name)
    cmd.add_argument("--output")
    for name in ("capture", "capture-read"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--config", required=True)
        cmd.add_argument("--operation", required=True)
        if name == "capture":
            cmd.add_argument("--request", required=True)
    for name in (
        "source-capture",
        "source-read",
        "source-active",
        "source-decision-read",
    ):
        cmd = commands.add_parser(name)
        cmd.add_argument("--config", required=True)
        cmd.add_argument("--operation", required=True)
        if name not in ("source-read", "source-decision-read"):
            cmd.add_argument("--request", required=True)
    args = parser.parse_args()
    try:
        if args.command == "smoke":
            from .fixture import smoke

            result = smoke(args.output)
        elif args.command in ("capture", "capture-read"):
            from .entry import load_request, run_capture

            request = load_request(args.request) if args.command == "capture" else None
            result = run_capture(args.config, args.operation, request)
        elif args.command == "source-decision-read":
            from .source_entry import read_source_decision

            result = read_source_decision(args.config, args.operation)
        elif args.command in ("source-capture", "source-read", "source-active"):
            from .entry import load_request
            from .source_entry import run_source_capture

            request = (
                None if args.command == "source-read" else load_request(args.request)
            )
            result = run_source_capture(
                args.config,
                args.operation,
                request if args.command == "source-capture" else None,
                active=request if args.command == "source-active" else None,
            )
        else:
            from .fixture import write_json
            from .report import build_report

            dataset = Dataset(load(args.dataset), Path(args.dataset).parent)
            result = build_report(
                load(args.manifest), dataset, load(args.traces), load(args.evaluator)
            )
            if args.output:
                write_json(args.output, result)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 2 if result.get("status") in ("failed", "unknown") else 0
    except (Invalid, OSError, ValueError, TypeError, KeyError, UnicodeError) as error:
        message = (
            str(error)
            if isinstance(error, Invalid)
            else "Malformed or unavailable input: " + type(error).__name__
        )
        print(
            json.dumps(
                {"status": "HOLD", "structural_validation": "FAIL", "reason": message}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
