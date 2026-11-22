"""Fail-closed runtime admission for the frozen index1159 continuation."""

import hashlib
import json
import os
from pathlib import Path


HERE = Path(__file__).resolve().parent
REQUEST = HERE / "REQUEST.json"
REQUIRED_ORIGINALS = (
    "host_observation_sha256",
    "allocation_sha256",
    "calendar_sha256",
    "runtime_sha256",
)


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def admit_runtime():
    """Return the request only after all external originals are bound."""

    request_raw = REQUEST.read_bytes()
    request = json.loads(request_raw)
    if request.get("actual_execution_authorized") is not True:
        raise SystemExit("authentic execution is not authorized before input read")
    if os.environ.get("HCSN_REQUEST_SHA256") != _sha256(request_raw):
        raise SystemExit("request digest mismatch before authentic input read")
    if os.environ.get("UNIQUE_EXECUTION_KEY") != request["execution_key"]:
        raise SystemExit("execution key mismatch before authentic input read")
    if os.environ.get("HCSN_ATTEMPT_ID") != "001":
        raise SystemExit("attempt mismatch before authentic input read")
    for field in REQUIRED_ORIGINALS:
        value = request["runtime_admission"][field]
        if not isinstance(value, str) or len(value) != 64:
            raise SystemExit(f"{field} is not frozen; numerical admission refused")
    if request["runtime_admission"]["concurrency"] not in (1, 2, 4):
        raise SystemExit("concurrency is not frozen")
    return request
