"""Verify exact bridge source, inherited identities, and zero-work HOLD."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_provider_fullstate_bridge import bridge


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_provider_fullstate_bridge"


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    for path, expected in {**freeze["files"], **freeze["bound_originals"]}.items():
        if _digest(ROOT / path) != expected:
            raise SystemExit(f"exact provider/full-state bridge input mismatch: {path}")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    result = freeze["frozen_result"]
    expected = {
        "coordinate_denominator": bridge.COORDINATE_DENOMINATOR,
        "execution_freeze_sha256": None,
        "execution_key": None,
        "historical_negative_and_unknown_preserved": True,
        "largegrid_qualification": False,
        "numerical_execution_allowed": False,
        "production_adoption": False,
        "provider_admitted": False,
        "status": "HOLD",
    }
    if any(request.get(name) != value for name, value in expected.items()):
        raise SystemExit("provider/full-state bridge request does not preserve HOLD")
    if sum(request["work_counts"].values()) != 0:
        raise SystemExit("provider/full-state bridge request reports numerical work")
    if (
        result["coordinate_denominator"] != bridge.COORDINATE_DENOMINATOR
        or result["frame_coordinates"] != bridge.FRAME_COORDINATES
        or result["frame_count"] != bridge.FRAME_COUNT
        or result["final_frame_coordinates"] != bridge.FINAL_FRAME_COORDINATES
        or result["n256_coordinates_written"] != 0
        or result["n256_frames_written"] != 0
        or result["largegrid_qualification"] is not False
        or result["all_closed"] is not False
    ):
        raise SystemExit("provider/full-state bridge frozen result mismatch")
    source = (PACKAGE / "bridge.py").read_text()
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
    if imported != {"dataclasses", "hashlib", "math", "struct"}:
        raise SystemExit("provider/full-state bridge has an unapproved import")
    forbidden = {
        "Popen",
        "backward",
        "expm",
        "expm_multiply",
        "open",
        "solve_ivp",
        "system",
    }
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names.update(node.id for node in ast.walk(tree) if isinstance(node, ast.Name))
    if names & forbidden:
        raise SystemExit("provider/full-state bridge exposes a forbidden call")
    print("PASS_CURRENTSTATE_N256_PROVIDER_FULLSTATE_BRIDGE_HOLD")


if __name__ == "__main__":
    main()
