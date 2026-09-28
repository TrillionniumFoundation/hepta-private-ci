#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "tools/hepta-engineering-control/control_engineering_v2/__init__.py"
MANIFEST = ROOT / "qualification/control-engineering/PUBLIC_API.json"


def names() -> list[str]:
    tree = ast.parse(INIT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            return sorted(ast.literal_eval(node.value))
    raise SystemExit("missing __all__")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    value = {
        "schema": "hepta.control-engineering-public-api.v1",
        "exports": names(),
    }
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if args.write:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(rendered, encoding="utf-8")
    if args.check and MANIFEST.read_text(encoding="utf-8") != rendered:
        raise SystemExit("control.engineering public API manifest drift")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
