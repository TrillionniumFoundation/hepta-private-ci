#!/usr/bin/env python3
"""Check the declared control.engineering package-root API snapshot."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/hepta-engineering-control/control_engineering_v2/__init__.py"
SNAPSHOT = ROOT / "tools/hepta-engineering-control/PUBLIC_API.json"


def public_api() -> list[str]:
    module = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if (
                not isinstance(value, list)
                or any(not isinstance(item, str) or not item for item in value)
                or len(value) != len(set(value))
            ):
                raise SystemExit("control.engineering __all__ is not a unique string list")
            return value
    raise SystemExit("control.engineering __all__ not found")


def rendered() -> str:
    return json.dumps(
        {
            "schema": "hepta.control-engineering-public-api.v1",
            "module": "control.engineering",
            "exports": public_api(),
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered()
    if args.write:
        SNAPSHOT.write_text(expected, encoding="utf-8")
    else:
        actual = SNAPSHOT.read_text(encoding="utf-8") if SNAPSHOT.is_file() else ""
        if actual != expected:
            raise SystemExit("control.engineering PUBLIC_API.json is stale")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
