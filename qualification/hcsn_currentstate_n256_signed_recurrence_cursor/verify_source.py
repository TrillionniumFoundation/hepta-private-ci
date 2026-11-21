"""Verify the frozen small-fixture signed recurrence cursor."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_signed_recurrence_cursor"
ALLOWED_IMPORTS = {
    "dataclasses",
    "fractions",
    "hashlib",
    "json",
    "pathlib",
    "qualification",
    "unittest",
}
FORBIDDEN_MARKERS = (
    "hcsn_currentstate_n256_original_artifact",
    "numpy",
    "scipy",
    "torch",
)


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
        request["authentic_n256_bundle_loaded"] is not False
        or request["authentic_provider_execution_allowed"] is not False
        or request["execution_key"] is not None
        or request["resource_gate_closed"] is not False
        or request["n256_qualified"] is not False
        or request["all_closed"] is not False
        or request["cause_of_6901_red"] != "UNKNOWN"
        or request["c2_full_replay_completed_fits"] != 0
        or request["hpca_status"] != "NoUpdate"
    ):
        raise SystemExit("request is not fail closed")

    for name in ("cursor.py", "test_cursor.py"):
        source = (PACKAGE / name).read_text()
        tree = ast.parse(source)
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
        if any(marker in source for marker in FORBIDDEN_MARKERS):
            raise SystemExit(f"forbidden authentic or numerical import marker: {name}")

    review = json.loads((PACKAGE / "REVIEW.json").read_text())
    scope = review["scope"]
    cold = review["cold_resume_fixture"]
    integrity = review["integrity_boundary"]
    if (
        scope["authentic_provider_calls"] != 0
        or scope["authentic_resource_profile"] is not False
        or scope["resource_gate_closed"] is not False
        or scope["n256_qualified"] is not False
        or scope["all_closed"] is not False
        or review["historical_statuses"]["6901_numerical_cause"] != "UNKNOWN"
        or cold["positive_saved_continuations"] != 20
        or cold["negative_saved_continuations"] != 20
        or cold["largest_encoded_cursor_bytes"] != 677
        or integrity["external_signature_or_custody"] is not False
        or integrity["hostile_body_and_digest_replacement_prevented"] is not False
    ):
        raise SystemExit("review scope is not fail closed")

    print("PASS_N256_SIGNED_RECURRENCE_CURSOR_SMALL_FIXTURE_SOURCE")


if __name__ == "__main__":
    main()
