"""Verify the frozen small-fixture signed streaming candidate."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_signed_streaming"
ALLOWED_IMPORTS = {
    "ast",
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

    for name in ("streaming.py", "test_streaming.py"):
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
    if (
        scope["authentic_provider_calls"] != 0
        or scope["authentic_resource_profile"] is not False
        or scope["resource_gate_closed"] is not False
        or scope["n256_qualified"] is not False
        or scope["all_closed"] is not False
        or review["historical_statuses"]["6901_numerical_cause"] != "UNKNOWN"
        or review["internal_liveness"]["maximum_live_parsed_vectors"] != 1
        or review["internal_liveness"]["result_retention_by_consumer_bounded"]
        is not False
    ):
        raise SystemExit("review scope is not fail closed")

    print("PASS_N256_SIGNED_STREAMING_SMALL_FIXTURE_SOURCE")


if __name__ == "__main__":
    main()
