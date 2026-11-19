"""Verify the separately frozen hosted zero-model observation source."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parent
REPO = ROOT.parents[1]


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    request = json.loads((ROOT / "REQUEST_V2.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE_V2.json").read_text())
    files = {
        "capture_sha256": ROOT / "capture.py",
        "request_sha256": ROOT / "REQUEST_V2.json",
        "request_v1_sha256": ROOT / "REQUEST.json",
        "requirements_sha256": ROOT / "requirements.txt",
        "source_freeze_v1_sha256": ROOT / "SOURCE_FREEZE.json",
        "tests_sha256": ROOT / "test_source.py",
        "verifier_sha256": ROOT / "verify_source.py",
        "workflow_sha256": REPO
        / ".github/workflows/hcsn-currentstate-n256-hosted-runtime-snapshot.yml",
        "snapshot_source_sha256": REPO
        / "qualification/hcsn_currentstate_n256_firststep_resource_snapshot/snapshot_source.py",
        "attempt001_job_log_b64_sha256": ROOT / "evidence/attempt001/JOB_LOG.txt.b64",
        "attempt001_terminal_sha256": ROOT / "evidence/attempt001/TERMINAL.json",
    }
    observed = {name: _sha(path) for name, path in files.items()}
    if any(freeze.get(name) != value for name, value in observed.items()):
        raise ValueError("source freeze mismatch")
    for name in ("capture_sha256", "snapshot_source_sha256"):
        if request[name] != observed[name]:
            raise ValueError("request/source mismatch")
    if request["base_commit"] != "6257d15ce0e260f56c7ff4c6afed1de986b95bb8":
        raise ValueError("parent head mismatch")
    if request["repair_parent_head"] != "481a42e729e866a923a8f74b0d7fc25dfbf85f0d":
        raise ValueError("repair parent mismatch")
    if request["prior_hosted_failures_preserved"] != [44252369558]:
        raise ValueError("hosted RED not preserved")
    if request["n256_numerical_execution_allowed"]:
        raise ValueError("unexpected numerical admission")
    if request["runtime_admitted"] or request["resource_admitted"]:
        raise ValueError("unexpected runtime or resource admission")
    return {
        "status": "PASS_SOURCE_FROZEN_HOSTED_ZERO_MODEL_HOLD_ADMISSION",
        "small_stdlib_tests": 5,
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
