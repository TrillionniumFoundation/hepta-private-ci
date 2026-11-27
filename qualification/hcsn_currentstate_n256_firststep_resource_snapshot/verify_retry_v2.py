"""Verify the frozen second observation request and preserved RED original."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parent
EVIDENCE = ROOT / "evidence" / "attempt001"
EVIDENCE_V2 = ROOT / "evidence" / "attempt002"


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    request = json.loads((ROOT / "REQUEST_V2.json").read_text())
    terminal = json.loads((EVIDENCE / "TERMINAL.json").read_text())
    start = json.loads((EVIDENCE / "PROCESS_START.json").read_text())
    stderr = (EVIDENCE / "STDERR.txt").read_text()
    terminal_v2 = json.loads((EVIDENCE_V2 / "TERMINAL.json").read_text())
    start_v2 = json.loads((EVIDENCE_V2 / "PROCESS_START.json").read_text())
    stderr_v2 = (EVIDENCE_V2 / "STDERR.txt").read_text()
    hold = json.loads((ROOT / "RUNTIME_HOLD.json").read_text())
    if request["snapshot_source_sha256"] != _sha(ROOT / "snapshot_source.py"):
        raise ValueError("v2 source mismatch")
    for name, expected in request["predecessor_evidence_sha256"].items():
        if _sha(EVIDENCE / name) != expected:
            raise ValueError(f"predecessor evidence mismatch: {name}")
    if request["base_commit"] != "0b03f43e7f20fdb50fa323ed1f555b26dd0d8c2b":
        raise ValueError("v2 parent head mismatch")
    if request["predecessor"]["job_id"] != terminal["job_id"]:
        raise ValueError("predecessor terminal mismatch")
    if start["job"]["id"] != terminal["job_id"]:
        raise ValueError("start/terminal mismatch")
    if terminal["state"] != "failed" or terminal["exit_code"] != 1:
        raise ValueError("predecessor RED was not preserved")
    if terminal["timed_out"] or terminal["cancelled"]:
        raise ValueError("predecessor failure classification mismatch")
    if terminal["log_bytes"]["stderr"] != {"seen": 476, "stored": 476}:
        raise ValueError("predecessor stderr count mismatch")
    if "numpy.__file__ was None" not in request["predecessor"]["failure"]:
        raise ValueError("predecessor failure missing")
    if "not 'NoneType'" not in stderr:
        raise ValueError("predecessor raw traceback missing")
    if "PYTHONNOUSERSITE" in request["environment"]:
        raise ValueError("v1 override unexpectedly retained")
    if start_v2["job"]["idempotency_key"] != request["idempotency_key"]:
        raise ValueError("v2 request/start key mismatch")
    if start_v2["job"]["id"] != terminal_v2["job_id"]:
        raise ValueError("v2 start/terminal mismatch")
    if terminal_v2["state"] != "failed" or terminal_v2["exit_code"] != 1:
        raise ValueError("v2 RED was not preserved")
    if terminal_v2["timed_out"] or terminal_v2["cancelled"]:
        raise ValueError("v2 failure classification mismatch")
    if terminal_v2["log_bytes"]["stderr"] != {"seen": 476, "stored": 476}:
        raise ValueError("v2 stderr count mismatch")
    if "not 'NoneType'" not in stderr_v2:
        raise ValueError("v2 raw traceback missing")
    if hold["status"] != "HOLD_RUNTIME_IDENTITY_REMEDIATION":
        raise ValueError("runtime HOLD missing")
    for name, expected in hold["attempt002_evidence_sha256"].items():
        if _sha(EVIDENCE_V2 / name) != expected:
            raise ValueError(f"v2 evidence mismatch: {name}")
    if hold["next_idempotency_key"] is not None or hold["resource_admitted"]:
        raise ValueError("unexpected retry or resource admission")
    if request["n256_numerical_execution_allowed"] or request["resource_admitted"]:
        raise ValueError("unexpected numerical admission")
    return {
        "status": "PASS_V2_FROZEN_PRESERVE_V1_RED_HOLD_RESOURCE_OBSERVATION",
        "predecessor_job_id": terminal["job_id"],
        "predecessor_state": terminal["state"],
        "n256_input_reads": 0,
        "dynamic_steps": 0,
        "matrix_exponential_actions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "resource_admitted": False,
        "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
