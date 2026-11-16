"""Verify exact compatibility-bridge source, inputs, and zero-work HOLD."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_execution_admission_bridge import (
    admission_bridge,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_execution_admission_bridge"


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    for path, expected in {**freeze["files"], **freeze["bound_originals"]}.items():
        if _digest(ROOT / path) != expected:
            raise SystemExit(f"exact execution/admission bridge input mismatch: {path}")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    expected = {
        "all_closed": False,
        "execution_freeze_sha256": None,
        "execution_key": None,
        "historical_negative_and_unknown_preserved": True,
        "largegrid_qualification": False,
        "legacy_provider_admission_schema": admission_bridge.LEGACY_PROVIDER_ADMISSION_SCHEMA,
        "numerical_execution_allowed": False,
        "production_adoption": False,
        "provider_admission_sha256": None,
        "provider_admitted": False,
        "status": "HOLD",
        "target_admission_schema": admission_bridge.CURRENT_ADMISSION_SCHEMA,
    }
    if any(request.get(name) != value for name, value in expected.items()):
        raise SystemExit("execution/admission bridge request does not preserve HOLD")
    if sum(request["work_counts"].values()) != 0:
        raise SystemExit("execution/admission bridge request reports numerical work")
    result = freeze["frozen_result"]
    if (
        result["legacy_provider_admission_schema"]
        != admission_bridge.LEGACY_PROVIDER_ADMISSION_SCHEMA
        or result["target_admission_schema"]
        != admission_bridge.CURRENT_ADMISSION_SCHEMA
        or result["future_originals_supplied"] != 0
        or result["provider_calls"] != 0
        or result["n256_coordinates_written"] != 0
        or result["largegrid_qualification"] is not False
        or result["all_closed"] is not False
    ):
        raise SystemExit("execution/admission bridge frozen result mismatch")
    source = (PACKAGE / "admission_bridge.py").read_text()
    tree = ast.parse(source)
    imported = {
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported.update(
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    if imported != {"dataclasses", "datetime", "qualification"}:
        raise SystemExit("execution/admission bridge has an unapproved import")
    forbidden = {
        "Popen",
        "backward",
        "expm",
        "expm_multiply",
        "open",
        "require_execution_admission",
        "solve_ivp",
        "synthetic_uniformization_action",
        "system",
        "write_n256_stream",
    }
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names.update(node.id for node in ast.walk(tree) if isinstance(node, ast.Name))
    if names & forbidden:
        raise SystemExit("execution/admission bridge exposes a forbidden call")
    print("PASS_CURRENTSTATE_N256_V2_EXECUTION_ADMISSION_BRIDGE_HOLD")


if __name__ == "__main__":
    main()
