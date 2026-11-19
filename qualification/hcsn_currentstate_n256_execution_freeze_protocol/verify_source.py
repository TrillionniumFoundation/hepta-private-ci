"""Verify exact execution-freeze protocol source and current HOLD."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_execution_freeze_protocol.execution_freeze import (
    EXTERNAL_NAMES,
    RESOURCE_NAMES,
    require_current_hold,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_execution_freeze_protocol"


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    for path, expected in {
        **freeze["files"],
        **freeze["bound_originals"],
    }.items():
        if _digest(ROOT / path) != expected:
            raise SystemExit(f"exact execution-freeze source mismatch: {path}")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    if not require_current_hold(request):
        raise SystemExit("execution-freeze protocol did not preserve HOLD")
    result = freeze["frozen_result"]
    if (
        request["parent_roster_resolved_request_sha256"]
        != freeze["bound_originals"][
            "qualification/hcsn_currentstate_n256_uniformization_roster_resolved_hold/REQUEST.json"
        ]
        or request["provider_source_sha256"]
        != freeze["bound_originals"][
            "qualification/hcsn_currentstate_n256_uniformization_provider_intent/provider.py"
        ]
        or len(request["future_originals"])
        != len(RESOURCE_NAMES) + len(EXTERNAL_NAMES) + 1
        or sum(value is not None for value in request["future_originals"].values())
        != result["future_originals_supplied"]
        or len(request["future_originals"])
        != result["future_originals_total"]
        or sum(request["work_counts"].values()) != result["work_calls"]
        or request["resource_bundle_admitted"]
        != result["resource_bundle_admitted"]
        or request["provider_admitted"] != result["provider_admitted"]
        or request["numerical_execution_allowed"]
        != result["numerical_execution_allowed"]
        or request["largegrid_qualification"] != result["largegrid_qualification"]
        or request["production_adoption"] != result["production_adoption"]
        or request["all_closed"] != result["all_closed"]
    ):
        raise SystemExit("execution-freeze frozen result mismatch")
    tree = ast.parse((PACKAGE / "execution_freeze.py").read_text())
    imported_roots = {
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported_roots.update(
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    if imported_roots != {"dataclasses", "datetime", "hashlib", "json", "re"}:
        raise SystemExit("execution-freeze protocol has an unapproved import")
    forbidden = {
        "Popen",
        "backward",
        "expm",
        "expm_multiply",
        "run",
        "solve_ivp",
        "step",
        "system",
    }
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names.update(node.id for node in ast.walk(tree) if isinstance(node, ast.Name))
    if names & forbidden:
        raise SystemExit("execution-freeze protocol exposes a forbidden call")
    print("PASS_CURRENTSTATE_N256_EXECUTION_FREEZE_PROTOCOL_HOLD")


if __name__ == "__main__":
    main()
