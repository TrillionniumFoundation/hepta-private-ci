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
    if freeze["base_head"] != "2bc052ff7193b41199733a00303ffe8c321db153":
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
    return freeze


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
