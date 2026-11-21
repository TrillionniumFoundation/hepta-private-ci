"""Verify the frozen authentic-input signed batch resource review."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_signed_batch_resource_review.review import (
    review,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_signed_batch_resource_review"
ALLOWED_IMPORTS = {
    "ast",
    "fractions",
    "hashlib",
    "json",
    "pathlib",
    "qualification",
    "unittest",
}
FORBIDDEN_CALLS = {
    "non_substochastic_signed_batch_outputs_from_fp64_intervals",
    "non_substochastic_signed_outputs_from_fp64_intervals",
    "_outputs_from_parsed",
    "_row_action",
    "expm",
    "expm_multiply",
    "matrix_exp",
    "backward",
    "step",
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
        or request["authentic_provider_execution_allowed"] is not False
        or request["execution_key"] is not None
        or request["resource_gate_closed"] is not False
        or request["n256_qualified"] is not False
        or request["largegrid_qualification"] is not False
        or request["all_closed"] is not False
        or request["cause_of_6901_red"] != "UNKNOWN"
        or request["authentic_batch_provider_calls"] != 0
        or request["authentic_recurrence_calls"] != 0
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
        if not FORBIDDEN_CALLS.isdisjoint(calls):
            raise SystemExit(f"numerical provider or recurrence call present: {name}")

    result = review()
    if (
        result["work"]["authentic_batch_provider_calls"] != 0
        or result["work"]["authentic_recurrence_calls"] != 0
        or result["finding"]["authentic_execution_admitted"] is not False
        or result["scope"]["n256_qualified"] is not False
        or result["scope"]["all_closed"] is not False
        or result["historical_statuses"]["cause_of_6901_red"] != "UNKNOWN"
    ):
        raise SystemExit("review scope is not fail closed")
    print("PASS_N256_AUTHENTIC_SIGNED_BATCH_RESOURCE_SOURCE")


if __name__ == "__main__":
    main()
