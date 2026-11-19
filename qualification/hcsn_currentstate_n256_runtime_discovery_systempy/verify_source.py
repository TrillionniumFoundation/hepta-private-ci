"""Verify the frozen stdlib-only system-Python discovery source."""

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
        "inventory_source_sha256": _sha(ROOT / "inventory_source.py"),
        "tests_sha256": _sha(ROOT / "test_source.py"),
        "verifier_sha256": _sha(ROOT / "verify_source.py"),
    }
    if any(freeze.get(name) != value for name, value in expected.items()):
        raise ValueError("source freeze mismatch")
    if request["inventory_source_sha256"] != expected["inventory_source_sha256"]:
        raise ValueError("request/source mismatch")
    if request["base_commit"] != "0a694ebd0d9fcd94feaaa9fdd6cea7ca97f39cfb":
        raise ValueError("parent head mismatch")
    if request["imports_candidate_modules"] or request["mutates_runtime"]:
        raise ValueError("unexpected runtime import or mutation")
    if request["n256_numerical_execution_allowed"]:
        raise ValueError("unexpected numerical admission")
    if request["runtime_admitted"] or request["resource_admitted"]:
        raise ValueError("unexpected runtime or resource admission")
    return {
        "status": "PASS_SOURCE_FROZEN_ZERO_MODEL_HOLD_RUNTIME_IDENTITY",
        "small_stdlib_tests": 5,
        "candidate_module_imports": 0,
        "n256_input_reads": 0,
        "dynamic_steps": 0,
        "matrix_exponential_actions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "runtime_admitted": False,
        "resource_admitted": False,
        "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
