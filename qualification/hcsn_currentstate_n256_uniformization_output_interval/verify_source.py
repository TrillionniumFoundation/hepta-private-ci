"""Verify the frozen positive rational interval source and HOLD boundary."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parent
REPOSITORY = ROOT.parents[1]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text(encoding="utf-8"))
    for relative_path, expected_sha256 in freeze["files"].items():
        if _sha256(REPOSITORY / relative_path) != expected_sha256:
            raise SystemExit(f"source freeze mismatch: {relative_path}")

    source = (ROOT / "output_interval.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    if imported & {"decimal", "numpy", "scipy"} or "float" in names:
        raise SystemExit("interval proof depends on a forbidden numeric conversion")
    for forbidden in (
        "uniformization_primitive",
        "sparse_dynamic_intent",
        "independent_oracle_intent",
    ):
        if forbidden in source:
            raise SystemExit(f"interval proof imports an existing numeric kernel: {forbidden}")

    request = json.loads((ROOT / "REQUEST.json").read_text(encoding="utf-8"))
    if request["schema"] != "hcsn-n256-uniformization-positive-output-interval-v1":
        raise SystemExit("request schema mismatch")
    if request["numerical_idempotency_key"] is not None:
        raise SystemExit("unexpected numerical idempotency key")
    if request["authentic_n256_execution_allowed"]:
        raise SystemExit("source-only stage enabled authentic N256 work")
    if any(request["execution_counts"].values()):
        raise SystemExit("authentic execution ledger is nonzero")
    if request["bounded_fixture_proofs_per_dual_mode_ci"] != 4:
        raise SystemExit("bounded fixture proof ledger mismatch")
    for closed_gate in (
        "exact_positive_rational_interval_certified",
        "binary64_unique_rounding_certified",
    ):
        if not request[closed_gate]:
            raise SystemExit(f"certificate missing: {closed_gate}")
    for open_gate in (
        "signed_vector_certified",
        "non_substochastic_certified",
        "decimal_uniformization_certified",
        "authentic_n256_bundle_loaded",
        "provider_qualified",
        "largegrid_qualification",
        "all_closed",
    ):
        if request[open_gate]:
            raise SystemExit(f"qualification boundary widened: {open_gate}")
    print("PASS_N256_UNIFORMIZATION_POSITIVE_OUTPUT_INTERVAL_SOURCE_ONLY")


if __name__ == "__main__":
    main()

