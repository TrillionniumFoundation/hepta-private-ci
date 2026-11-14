"""Run with PYTHONPATH=scripts python -m perc1 ..."""

import argparse
import json
import sys
from pathlib import Path

from .fixture import smoke, write_json
from .report import build_report
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
    args = parser.parse_args()
    try:
        if args.command == "smoke":
            result = smoke(args.output)
        else:
            dataset = Dataset(load(args.dataset), Path(args.dataset).parent)
            result = build_report(
                load(args.manifest), dataset, load(args.traces), load(args.evaluator)
            )
            if args.output:
                write_json(args.output, result)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
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
