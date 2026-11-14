import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parent
REPOSITORY = ROOT.parents[1]
FREEZE = ROOT / "SOURCE_FREEZE.json"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    for relative_path, expected_sha256 in freeze["files"].items():
        path = REPOSITORY / relative_path
        if _sha256(path) != expected_sha256:
            raise SystemExit(f"source freeze mismatch: {relative_path}")

    source_path = ROOT / "fp64_mul_div.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    forbidden_imports = {"struct", "fractions", "numpy", "scipy"}
    if imported & forbidden_imports or "float" in names:
        raise SystemExit("mul/div primitive depends on a forbidden numeric conversion")
    for forbidden in freeze["forbidden_source_tokens"]:
        if forbidden in source:
            raise SystemExit(f"forbidden source token: {forbidden}")

    request = json.loads((ROOT / "REQUEST.json").read_text(encoding="utf-8"))
    expected_zero = {
        "dynamic_n256_calls": 0,
        "model_calls": 0,
        "optimizer_calls": 0,
        "torch_calls": 0,
    }
    if any(request[key] != value for key, value in expected_zero.items()):
        raise SystemExit("zero-execution ledger mismatch")
    if request["numerical_idempotency_key"] is not None:
        raise SystemExit("unexpected numerical idempotency key")
    if not request["finite_mul_div_single_round_certified"]:
        raise SystemExit("mul/div source certificate missing")
    if request["add_sub_fma_sequence_certified"]:
        raise SystemExit("add/sub/FMA sequencing must remain OPEN")
    if request["provider_qualified"] or request["all_closed"]:
        raise SystemExit("qualification boundary widened")
    print("PASS_N256_EXACT_BINARY64_MUL_DIV_SOURCE_ONLY")


if __name__ == "__main__":
    main()
