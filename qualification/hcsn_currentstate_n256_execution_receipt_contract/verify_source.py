"""Verify exact receipt-contract source, inputs, and zero-work HOLD."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_execution_receipt_contract import (
    receipt_contract,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_execution_receipt_contract"


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    for path, expected in {**freeze["files"], **freeze["bound_originals"]}.items():
        if _digest(ROOT / path) != expected:
            raise SystemExit(f"exact receipt-contract input mismatch: {path}")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    expected = {
        "all_closed": False,
        "execution_key": None,
        "future_execution_receipt_sha256": None,
        "future_result_manifest_sha256": None,
        "historical_negative_and_unknown_preserved": True,
        "largegrid_qualification": False,
        "numerical_execution_allowed": False,
        "production_adoption": False,
        "status": "HOLD",
    }
    if any(request.get(name) != value for name, value in expected.items()):
        raise SystemExit("execution-receipt request does not preserve HOLD")
    if sum(request["work_counts"].values()) != 0:
        raise SystemExit("execution-receipt request reports numerical work")
    result = freeze["frozen_result"]
    if (
        result["future_originals_supplied"] != 0
        or result["authentic_execution_receipts"] != 0
        or result["provider_calls"] != 0
        or result["n256_coordinates_written"] != 0
        or result["largegrid_qualification"] is not False
        or result["all_closed"] is not False
    ):
        raise SystemExit("execution-receipt frozen result mismatch")
    tree = ast.parse((PACKAGE / "receipt_contract.py").read_text())
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
    if imported != {"dataclasses", "datetime", "hashlib", "json", "qualification", "re"}:
        raise SystemExit("execution-receipt contract has an unapproved import")
    forbidden = {
        "Popen",
        "backward",
        "expm",
        "expm_multiply",
        "open",
        "solve_ivp",
        "synthetic_uniformization_action",
        "system",
        "write_n256_stream",
    }
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names.update(node.id for node in ast.walk(tree) if isinstance(node, ast.Name))
    if names & forbidden:
        raise SystemExit("execution-receipt contract exposes a forbidden call")
    if receipt_contract.SCHEMA != "hcsn-n256-uniformization-execution-receipt-v1":
        raise SystemExit("execution-receipt schema changed")
    print("PASS_CURRENTSTATE_N256_EXECUTION_RECEIPT_CONTRACT_HOLD")


if __name__ == "__main__":
    main()
