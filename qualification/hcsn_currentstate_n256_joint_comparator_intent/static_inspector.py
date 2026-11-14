"""Stdlib-only audit of the N256 joint comparator source intent."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

from .contract import validate_source_request


BOUND_SOURCES = {
    "candidate_source_sha256": "hcsn_currentstate_n256_sparse_dynamic_intent/sparse_dynamic.py",
    "oracle_source_sha256": "hcsn_currentstate_n256_independent_oracle_intent/independent_oracle.py",
    "serializer_source_sha256": "hcsn_currentstate_n256_canonical_serializer_intent/canonical_serializer.py",
    "resource_snapshot_source_freeze_sha256": "hcsn_currentstate_n256_resource_snapshot/SOURCE_FREEZE.json",
}
SOURCE_FILES = (
    "contract.py",
    "full_coordinate_comparator.py",
    "joint_runner_contract.py",
)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(package_root, qualification_root):
    package_root = Path(package_root)
    qualification_root = Path(qualification_root)
    request = validate_source_request(json.loads((package_root / "REQUEST.json").read_text()))
    imports = []
    for name in SOURCE_FILES:
        path = package_root / name
        source = ast.parse(path.read_text(), filename=str(path))
        compile(source, str(path), "exec")
        for node in ast.walk(source):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
    forbidden = ("numpy", "scipy", "torch")
    if any(
        name == prefix or name.startswith(prefix + ".")
        for name in imports
        for prefix in forbidden
    ):
        raise ValueError("source contract must remain stdlib-only")
    for field, relative in BOUND_SOURCES.items():
        if request[field] != _digest(qualification_root / relative):
            raise ValueError(f"{field} does not bind the frozen source")
    return {
        "schema": "hcsn-n256-joint-comparator-static-audit-v1",
        "status": "PASS_SOURCE_INTENT_HOLD_NUMERICAL",
        "coordinate_denominator": request["coordinate_denominator"],
        "capsules": request["capsules"],
        "new_numerical_idempotency_keys": 0,
        "n256_dynamic_runs": 0,
        "matrix_exponential_actions": 0,
        "candidate_calls": 0,
        "oracle_calls": 0,
        "n256_serializer_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "future_reference_interface_required": True,
        "largegrid_qualification": False,
        "all_closed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--qualification-root", required=True)
    arguments = parser.parse_args()
    print(json.dumps(inspect(arguments.package_root, arguments.qualification_root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
