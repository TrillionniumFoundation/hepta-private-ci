import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parent
FREEZE = ROOT / "SOURCE_FREEZE.json"


def main():
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    for relative, expected in freeze["sha256"].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"source hash mismatch: {relative}: {actual}")
    source = (ROOT / "fp64_exact.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    if "float" in names:
        raise SystemExit("primitive may not construct a binary float")
    if freeze["executed_counts"] != {
        "n256_candidate_calls": 0,
        "n256_dynamic_calls": 0,
        "n256_oracle_calls": 0,
        "optimizer_calls": 0,
        "torch_calls": 0,
    }:
        raise SystemExit("unexpected execution ledger")
    print("PASS_N256_EXACT_FP64_INPUT_CONVERSION_SOURCE_ONLY")


if __name__ == "__main__":
    main()

