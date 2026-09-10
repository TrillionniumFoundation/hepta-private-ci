#!/usr/bin/env python3
"""Verify Lane A current truth and emit exact-candidate receipts."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lane_a_foundation_lib import *  # noqa: F403


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify")
    commands.add_parser("self-test")
    for name in ("source-receipt", "native-receipt"):
        command = commands.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--expected-sha")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_matrix(read_json(MATRIX_PATH))  # noqa: F405
        elif args.command == "self-test":
            self_test()  # noqa: F405
        else:
            write_receipt(  # noqa: F405
                args.output,
                args.expected_sha,
                native=args.command == "native-receipt",
            )
    except VerificationError as error:  # noqa: F405
        print(f"lane-a-foundation verification failed: {error}", file=sys.stderr)
        return 1
    print(f"lane-a-foundation {args.command}: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
