#!/usr/bin/env python3
"""Verify only the memory.federation implementation map with the canonical verifier.

The repository-wide verifier remains the authority for global convergence.  The
module qualification lane reuses that exact implementation and narrows only the
MODULES.json view, so unrelated historical source anchors cannot invalidate an
otherwise fixed memory.federation candidate or deterministic merge tree.
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys
from types import ModuleType
from typing import Any

MODULE_ID = "memory.federation"
ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CANONICAL_VERIFIER = SCRIPTS / "hepta-implementation-maps.py"


def _load_canonical_verifier() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "hepta_implementation_maps_scoped", CANONICAL_VERIFIER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load canonical implementation-map verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scope_modules(module: ModuleType) -> None:
    original_load = module.load

    def scoped_load(relative: str) -> Any:
        value = original_load(relative)
        if relative != "docs/modules/MODULES.json":
            return value
        if not isinstance(value, dict) or not isinstance(value.get("modules"), list):
            raise RuntimeError("canonical module registry is malformed")
        selected = [row for row in value["modules"] if row.get("id") == MODULE_ID]
        if len(selected) != 1:
            raise RuntimeError(f"expected exactly one {MODULE_ID} registry entry")
        scoped = dict(value)
        scoped["modules"] = selected
        return scoped

    module.load = scoped_load


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-tree", required=True)
    args = parser.parse_args()

    verifier = _load_canonical_verifier()
    _scope_modules(verifier)
    verifier.verify(expected_sha=args.expected_sha, expected_tree=args.expected_tree)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
