"""Verify the frozen zero-provider resource review."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_signed_resource_review.review import (
    review,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_signed_resource_review"
ALLOWED_IMPORTS = {
    "ast",
    "fractions",
    "hashlib",
    "json",
    "math",
    "pathlib",
    "qualification",
    "struct",
    "unittest",
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
        or request["resource_gate_closed"] is not False
        or request["n256_qualified"] is not False
        or request["cause_of_6901_red"] != "UNKNOWN"
        or request["provider_calls"] != 0
        or request["dynamic_steps"] != 0
        or request["exponential_actions"] != 0
        or request["torch_calls"] != 0
        or request["optimizer_steps"] != 0
    ):
        raise SystemExit("request is not fail closed")

    for name in ("review.py", "test_review.py"):
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
            raise SystemExit(f"unexpected import: {name}")
        calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        forbidden = {
            "non_substochastic_signed_outputs_from_fp64_intervals",
            "expm",
            "expm_multiply",
            "matrix_exp",
            "backward",
            "step",
        }
        if not forbidden.isdisjoint(calls):
            raise SystemExit(f"numerical provider call present: {name}")

    if review() != json.loads((PACKAGE / "REVIEW.json").read_text()):
        raise SystemExit("frozen review mismatch")
    print("PASS_N256_AUTHENTIC_SIGNED_RESOURCE_SOURCE")


if __name__ == "__main__":
    main()
