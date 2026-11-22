"""Fail-closed runtime admission for the frozen index1159 continuation."""

import hashlib
import json
import math
import os
import stat
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
REQUEST = HERE / "REQUEST.json"
SOURCE_FREEZE = HERE / "SOURCE_FREEZE.json"
ORIGINAL_SCHEMAS = {
    "host_observation": "hcsn-tail1159-host-observation-v1",
    "allocation": "hcsn-tail1159-allocation-v1",
    "calendar": "hcsn-tail1159-calendar-v1",
    "runtime": "hcsn-tail1159-runtime-v1",
}
MAX_JSON_BYTES = 65536


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite JSON number")
    return result


def _reject_constant(value):
    raise ValueError(f"nonfinite JSON constant: {value}")


def _strict_json(raw, label):
    try:
        result = json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise SystemExit(f"{label} is not strict unambiguous JSON") from error
    if not isinstance(result, dict):
        raise SystemExit(f"{label} is not a JSON object")
    return result


def _bounded_regular_bytes(path, label):
    try:
        metadata = path.lstat()
    except OSError as error:
        raise SystemExit(f"{label} cannot be read before authentic input") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise SystemExit(f"{label} is not a single-link regular file")
    if metadata.st_size > MAX_JSON_BYTES:
        raise SystemExit(f"{label} exceeds the frozen JSON byte cap")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise SystemExit(f"{label} cannot be read before authentic input") from error
    if len(raw) != metadata.st_size:
        raise SystemExit(f"{label} changed while being read")
    return raw


def _parse_utc(value, field):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SystemExit(f"{field} is not a frozen UTC timestamp")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise SystemExit(f"{field} is not a valid UTC timestamp") from error


def _read_original(request, kind):
    admission = request["runtime_admission"]
    relative = admission[f"{kind}_path"]
    expected = admission[f"{kind}_sha256"]
    if not isinstance(relative, str):
        raise SystemExit(f"{kind}_path is not frozen; numerical admission refused")
    relative_path = Path(relative)
    if (
        relative_path.is_absolute()
        or len(relative_path.parts) != 2
        or relative_path.parts[0] != "runtime_originals"
        or relative_path.suffix != ".json"
    ):
        raise SystemExit(f"{kind}_path is outside the frozen originals directory")
    if not isinstance(expected, str) or len(expected) != 64:
        raise SystemExit(f"{kind}_sha256 is not frozen; numerical admission refused")
    raw = _bounded_regular_bytes(REQUEST.parent / relative_path, f"{kind} original")
    if _sha256(raw) != expected:
        raise SystemExit(f"{kind} original digest mismatch before authentic input read")
    original = _strict_json(raw, f"{kind} original")
    if original.get("schema") != ORIGINAL_SCHEMAS[kind]:
        raise SystemExit(f"{kind} original schema mismatch")
    for field, expected_value in {
        "identity": request["identity"],
        "execution_key": request["execution_key"],
        "intent_source_head": request["intent_source_head"],
        "source_manifest_sha256": _sha256(SOURCE_FREEZE.read_bytes()),
        "input_sha256": request["input"]["index537_collector_sha256"],
        "host": "desktop",
    }.items():
        if original.get(field) != expected_value:
            raise SystemExit(f"{kind} original {field} mismatch")
    return original


def _validate_originals(request, originals):
    admission = request["runtime_admission"]
    concurrency = admission["concurrency"]
    if concurrency not in (1, 2, 4):
        raise SystemExit("concurrency is not frozen")

    allocation = originals["allocation"]
    if allocation.get("concurrency") != concurrency:
        raise SystemExit("allocation concurrency mismatch")
    if not isinstance(allocation.get("allocation_id"), str) or not allocation["allocation_id"]:
        raise SystemExit("allocation identity is not frozen")
    if not isinstance(allocation.get("authority"), str) or not allocation["authority"]:
        raise SystemExit("allocation authority is not frozen")
    memory_bytes = allocation.get("memory_bytes")
    if not isinstance(memory_bytes, int) or isinstance(memory_bytes, bool):
        raise SystemExit("allocation memory is not an integer")
    if memory_bytes < request["checkpoint_caps"]["aggregate_compact_bytes"]:
        raise SystemExit("allocation memory is below the frozen checkpoint cap")

    calendar = originals["calendar"]
    if not isinstance(calendar.get("calendar_id"), str) or not calendar["calendar_id"]:
        raise SystemExit("calendar identity is not frozen")
    if calendar.get("allocation_id") != allocation["allocation_id"]:
        raise SystemExit("calendar allocation identity mismatch")
    start = _parse_utc(calendar.get("valid_from_utc"), "calendar valid_from_utc")
    end = _parse_utc(calendar.get("valid_until_utc"), "calendar valid_until_utc")
    now = datetime.now(timezone.utc)
    if not start <= now <= end:
        raise SystemExit("calendar window is not currently valid")

    observation = originals["host_observation"]
    observed = _parse_utc(observation.get("observed_at_utc"), "observation observed_at_utc")
    expires = _parse_utc(observation.get("expires_at_utc"), "observation expires_at_utc")
    if not observed <= now <= expires:
        raise SystemExit("host observation is not currently valid")
    headroom = observation.get("ancestor_cgroup_headroom_bytes")
    if not isinstance(headroom, int) or isinstance(headroom, bool):
        raise SystemExit("observed cgroup headroom is not an integer")
    if headroom < memory_bytes:
        raise SystemExit("observed cgroup headroom is below the allocation")

    runtime = originals["runtime"]
    if not isinstance(runtime.get("runtime_id"), str) or not runtime["runtime_id"]:
        raise SystemExit("runtime identity is not frozen")
    for field in ("python_executable_sha256", "dependency_manifest_sha256"):
        value = runtime.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise SystemExit(f"runtime {field} is not frozen")


def admit_runtime():
    """Return the request only after all external originals are bound."""

    request_raw = _bounded_regular_bytes(REQUEST, "request")
    request = _strict_json(request_raw, "request")
    if request.get("actual_execution_authorized") is not True:
        raise SystemExit("authentic execution is not authorized before input read")
    if os.environ.get("HCSN_REQUEST_SHA256") != _sha256(request_raw):
        raise SystemExit("request digest mismatch before authentic input read")
    if os.environ.get("UNIQUE_EXECUTION_KEY") != request["execution_key"]:
        raise SystemExit("execution key mismatch before authentic input read")
    if os.environ.get("HCSN_ATTEMPT_ID") != "001":
        raise SystemExit("attempt mismatch before authentic input read")
    originals = {kind: _read_original(request, kind) for kind in ORIGINAL_SCHEMAS}
    _validate_originals(request, originals)
    return request
