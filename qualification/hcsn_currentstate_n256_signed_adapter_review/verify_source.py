"""Verify the authentic N256 signed-provider adapter review source."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_signed_adapter_review.adapter import (
    review,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_signed_adapter_review"
ALLOWED_IMPORTS = {
    "ast",
    "hashlib",
    "json",
    "math",
    "pathlib",
    "struct",
    "unittest",
    "zipfile",
}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    for relative, expected in freeze["files"].items():
        if _digest(ROOT / relative) != expected:
            raise SystemExit(f"exact source mismatch: {relative}")
    for relative, expected in freeze["inputs"].items():
        if _digest(ROOT / relative) != expected:
            raise SystemExit(f"exact input mismatch: {relative}")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    if (
        request["numerical_execution_allowed"] is not False
        or request["execution_key"] is not None
        or request["adapter_admitted"] is not False
        or request["n256_qualified"] is not False
        or request["cause_of_6901_red"] != "UNKNOWN"
        or request["dynamic_steps"] != 0
        or request["exponential_actions"] != 0
        or request["provider_calls"] != 0
        or request["torch_calls"] != 0
        or request["optimizer_steps"] != 0
    ):
        raise SystemExit("request is not fail closed")

    for name in ("adapter.py", "test_adapter.py"):
        tree = ast.parse((PACKAGE / name).read_text())
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
        )
        if not imports <= ALLOWED_IMPORTS:
            raise SystemExit(f"non-standard numerical import: {name}")
        calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        forbidden = {"expm", "expm_multiply", "matrix_exp", "backward", "step"}
        if not forbidden.isdisjoint(calls):
            raise SystemExit(f"propagation call present: {name}")

    result = review()
    if result != json.loads((PACKAGE / "REVIEW.json").read_text()):
        raise SystemExit("frozen review mismatch")
    print("PASS_N256_AUTHENTIC_SIGNED_ADAPTER_SOURCE")


if __name__ == "__main__":
    main()
