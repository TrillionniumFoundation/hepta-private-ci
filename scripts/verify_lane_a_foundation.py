#!/usr/bin/env python3
"""Verify Lane A current truth and emit exact-candidate receipts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lane_a_foundation_lib import *  # noqa: F403


def _module_order_diagnostic() -> str:
    """Return an exact, side-effect-free snapshot for closed-world failures."""

    matrix = read_json(MATRIX_PATH)  # noqa: F405
    modules: Any = matrix.get("modules")
    row_types = (
        [type(row).__name__ for row in modules]
        if isinstance(modules, list)
        else type(modules).__name__
    )
    observed = (
        [row.get("module") for row in modules if isinstance(row, dict)]
        if isinstance(modules, list)
        else None
    )
    expected = list(EXPECTED_MODULES)  # noqa: F405
    return (
        f"matrix={MATRIX_PATH}; observed={observed!r}; expected={expected!r}; "
        f"row_types={row_types!r}; module_coverage={matrix.get('moduleCoverage')!r}"
    )


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
        suffix = ""
        if "closed-world module order mismatch" in str(error):
            try:
                suffix = f"; {_module_order_diagnostic()}"
            except Exception as diagnostic_error:  # pragma: no cover - CI diagnostic
                suffix = f"; diagnostic_failed={diagnostic_error!r}"
        print(
            f"lane-a-foundation verification failed: {error}{suffix}",
            file=sys.stderr,
        )
        return 1
    print(f"lane-a-foundation {args.command}: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
