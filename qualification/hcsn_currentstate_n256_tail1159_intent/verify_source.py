"""Verify the exact source-only freeze without importing candidate code."""

import ast
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FREEZE = HERE / "SOURCE_FREEZE.json"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def verify():
    freeze = json.loads(FREEZE.read_text())
    if freeze["status"] != "SOURCE_ONLY_RESOURCE_HOLD":
        raise SystemExit("source freeze status differs")
    if freeze["base_head"] != "0234bf0edf6c02dd1165b6ce635727b2ba599721":
        raise SystemExit("base head differs")
    for relative, expected in freeze["files"].items():
        raw = (REPO / relative).read_bytes()
        if _sha256(raw) != expected:
            raise SystemExit(f"frozen source differs: {relative}")
        if relative.endswith(".py"):
            ast.parse(raw, filename=relative)
    request = json.loads((HERE / "REQUEST.json").read_text())
    admission = request["runtime_admission"]
    if request["actual_execution_authorized"]:
        raise SystemExit("source-only intent claims execution authorization")
    if admission != {
        "allocation_path": None,
        "allocation_sha256": None,
        "calendar_path": None,
        "calendar_sha256": None,
        "concurrency": None,
        "host_observation_path": None,
        "host_observation_sha256": None,
        "runtime_path": None,
        "runtime_sha256": None,
    }:
        raise SystemExit("runtime originals were changed")
    if request["budget"]["recurrence_row_actions"] != 6220:
        raise SystemExit("recurrence denominator differs")
    if request["budget"]["semantic_checkpoint_parses"] != 10:
        raise SystemExit("semantic checkpoint parse denominator differs")
    if request["budget"]["canonical_raw_reencodes"] != 10:
        raise SystemExit("canonical raw reencode denominator differs")
    if request["lane_log_caps"] != {
        "stderr_bytes": 1048576,
        "stdout_bytes": 1048576,
    }:
        raise SystemExit("lane log caps differ")
    if request["identity"] != freeze["identity"]:
        raise SystemExit("request and source-freeze identities differ")
    return freeze


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
