"""Verify the immutable system-Python discovery failure without execution."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parent
ATTEMPT = ROOT / "evidence" / "attempt001"


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    hold = json.loads((ROOT / "RUNTIME_HOLD.json").read_text())
    start = json.loads((ATTEMPT / "PROCESS_START.json").read_text())
    terminal = json.loads((ATTEMPT / "TERMINAL.json").read_text())
    stderr = (ATTEMPT / "STDERR.txt").read_bytes()
    observed = {
        name: _sha(ATTEMPT / name)
        for name in ("PROCESS_START.json", "STDERR.txt", "TERMINAL.json")
    }
    if hold["attempt001_evidence_sha256"] != observed:
        raise ValueError("attempt evidence hash mismatch")
    if start["job"]["id"] != terminal["job_id"] or terminal["job_id"] != hold["job_id"]:
        raise ValueError("job identity mismatch")
    if start["job"]["idempotency_key"] != hold["idempotency_key"]:
        raise ValueError("idempotency key mismatch")
    if terminal["state"] != "failed" or terminal["exit_code"] != 1:
        raise ValueError("unexpected terminal state")
    if terminal["timed_out"] or terminal["cancelled"]:
        raise ValueError("unexpected timeout or cancellation")
    if terminal["log_bytes"]["stdout"] != {"seen": 0, "stored": 0}:
        raise ValueError("unexpected stdout ledger")
    if terminal["log_bytes"]["stderr"] != {"seen": 218, "stored": 218}:
        raise ValueError("unexpected stderr ledger")
    if len(stderr) != 218 or not stderr.endswith(
        b"ValueError: numpy distribution file list unavailable\n"
    ):
        raise ValueError("unexpected stderr bytes")
    for name in (
        "candidate_module_imports",
        "n256_input_reads",
        "n256_serializer_calls",
        "dynamic_steps",
        "matrix_exponential_actions",
        "torch_calls",
        "optimizer_steps",
    ):
        if hold[name] != 0:
            raise ValueError(f"nonzero execution count: {name}")
    if any(hold[name] for name in ("runtime_candidate_eligible", "runtime_admitted", "resource_admitted", "all_closed")):
        raise ValueError("unexpected admission")
    return {
        "status": "PASS_PRESERVED_REAL_RED_HOLD_RUNTIME_IDENTITY",
        "job_id": terminal["job_id"],
        "exit_code": terminal["exit_code"],
        "stdout_bytes": 0,
        "stderr_bytes": 218,
        "numerical_actions": 0,
        "runtime_admitted": False,
        "resource_admitted": False,
        "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
