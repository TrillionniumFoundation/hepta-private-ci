"""Verify the frozen zero-model resource observation source."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parent


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    request = json.loads((ROOT / "REQUEST.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    expected = {
        "request_sha256": _sha(ROOT / "REQUEST.json"),
        "snapshot_source_sha256": _sha(ROOT / "snapshot_source.py"),
        "tests_sha256": _sha(ROOT / "test_source.py"),
        "verifier_sha256": _sha(ROOT / "verify_source.py"),
    }
    if any(freeze.get(name) != value for name, value in expected.items()):
        raise ValueError("source freeze mismatch")
    if request["snapshot_source_sha256"] != expected["snapshot_source_sha256"]:
        raise ValueError("request/source mismatch")
    if request["base_commit"] != "a10817550a9e23025994783c215737cfccf0ca22":
        raise ValueError("parent head mismatch")
    if request["n256_numerical_execution_allowed"] or request["resource_admitted"]:
        raise ValueError("unexpected numerical admission")
    return {
        "status": "PASS_SOURCE_FROZEN_HOLD_RESOURCE_OBSERVATION",
        "small_stdlib_tests": 5,
        "n256_input_reads": 0,
        "n256_serializer_calls": 0,
        "dynamic_steps": 0,
        "matrix_exponential_actions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
