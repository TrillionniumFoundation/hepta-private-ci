"""Verify the frozen zero-model index1159 resource observation source."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXPECTED_SOURCE_SHA256 = (
    "8b351c27099a40079c26c0b79ea06e6900841d03f1277a073bf1b92f6477a973"
)
EXPECTED_REQUEST_SHA256 = (
    "6d913f77572bbadc85a67e4e853cfbbfd635834f4aa487791a78ef09f41d3d73"
)
EXPECTED_IDENTITY = "hcsn-index1159-current-resource-observation-20261122-c6bc-v1"
EXPECTED_KEY = "hcsn-index1159-current-resource-observation-20261122-c6bc-001"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def verify():
    source = (ROOT / "snapshot_source.sh").read_bytes()
    request_raw = (ROOT / "REQUEST.json").read_bytes()
    request = json.loads(request_raw)
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    if _sha256(source) != EXPECTED_SOURCE_SHA256:
        raise SystemExit("snapshot source bytes differ")
    if request["source_sha256"] != EXPECTED_SOURCE_SHA256:
        raise SystemExit("request source digest differs")
    if _sha256(request_raw) != EXPECTED_REQUEST_SHA256:
        raise SystemExit("request bytes differ")
    if freeze["request_sha256"] != EXPECTED_REQUEST_SHA256:
        raise SystemExit("source freeze request digest differs")
    if freeze["source_sha256"] != EXPECTED_SOURCE_SHA256:
        raise SystemExit("source freeze source digest differs")
    if freeze["remote_execution_count_at_freeze"] != 0:
        raise SystemExit("source was not frozen before execution")
    if request["identity"] != EXPECTED_IDENTITY:
        raise SystemExit("request identity differs")
    if request["execution_key"] != EXPECTED_KEY:
        raise SystemExit("execution key differs")
    if request["execution_host"] != "desktop" or request["shell"] != "/bin/sh":
        raise SystemExit("host or shell differs")
    if request["timeout_seconds"] != 30 or request["memory_max_bytes"] is not None:
        raise SystemExit("resource observation launch parameters differ")
    if request["index1159_execution_authorized"]:
        raise SystemExit("index1159 execution must remain unauthorized")
    if request["remote_numeric_work_allowed"]:
        raise SystemExit("numeric work must remain prohibited")
    if request["allocation_contract"] is not None:
        raise SystemExit("allocation must remain absent")
    if request["calendar_contract"] is not None:
        raise SystemExit("calendar must remain absent")
    if any(request["work_caps"].values()):
        raise SystemExit("all numerical work caps must remain zero")
    text = source.decode()
    required = (
        "/proc/meminfo",
        "/proc/pressure/memory",
        "/proc/self/cgroup",
        "memory.current",
        "memory.max",
        "memory.events",
        "pids.current",
        "cpu.max",
    )
    if not all(fragment in text for fragment in required):
        raise SystemExit("required observation field differs")
    forbidden = ("rm ", "mv ", "cp ", "curl ", "wget ", "sudo ", "systemctl ")
    if any(fragment in text for fragment in forbidden):
        raise SystemExit("mutating or network command present")
    return {
        "identity": EXPECTED_IDENTITY,
        "source_sha256": EXPECTED_SOURCE_SHA256,
        "status": "SOURCE_FROZEN_REMOTE_NOT_EXECUTED",
        "remote_jobs": 0,
        "numeric_actions": 0,
        "resource_admitted": False,
        "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))

