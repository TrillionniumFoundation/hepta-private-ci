"""Verify the frozen input bridge and fail-closed qualification boundary."""

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
        path = REPOSITORY / relative_path
        if _sha256(path) != expected_sha256:
            raise SystemExit(f"source freeze mismatch: {relative_path}")

    source = (ROOT / "bridge.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    if imported & {"struct", "fractions", "numpy", "scipy"} or "float" in names:
        raise SystemExit("bridge depends on a forbidden numeric conversion")

    request = json.loads((ROOT / "REQUEST.json").read_text(encoding="utf-8"))
    if request["schema"] != "hcsn-n256-uniformization-exact-fp64-input-bridge-v1":
        raise SystemExit("request schema mismatch")
    if request["numerical_idempotency_key"] is not None:
        raise SystemExit("unexpected numerical idempotency key")
    if request["authentic_n256_execution_allowed"]:
        raise SystemExit("source-only stage enabled authentic N256 work")
    if any(request["execution_counts"].values()):
        raise SystemExit("authentic execution ledger is nonzero")
    if request["bounded_fixture_uniformization_calls_per_dual_mode_ci"] != 6:
        raise SystemExit("bounded fixture call ledger mismatch")
    if not request["exact_fp64_input_bridge_certified"]:
        raise SystemExit("exact input bridge certificate missing")
    for open_gate in (
        "uniformization_output_rounding_certified",
        "authentic_n256_bundle_loaded",
        "provider_qualified",
        "largegrid_qualification",
        "all_closed",
    ):
        if request[open_gate]:
            raise SystemExit(f"qualification boundary widened: {open_gate}")
    print("PASS_N256_UNIFORMIZATION_EXACT_FP64_INPUT_BRIDGE_SOURCE_ONLY")


if __name__ == "__main__":
    main()

