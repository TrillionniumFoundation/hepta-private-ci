"""Fail-closed runtime admission for the frozen index1159 continuation."""

import hashlib
from importlib import metadata
import json
import math
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
REQUEST = HERE / "REQUEST.json"
SOURCE_FREEZE = HERE / "SOURCE_FREEZE.json"
ORIGINAL_SCHEMAS = {
    "host_observation": "hcsn-tail1159-host-observation-v1",
    "allocation": "hcsn-tail1159-allocation-v1",
    "calendar": "hcsn-tail1159-calendar-v1",
    "runtime": "hcsn-tail1159-runtime-v1",
}
MAX_JSON_BYTES = 65536
MAX_EXECUTABLE_BYTES = 67108864
DEPENDENCY_MANIFEST_FORMAT = "importlib-name-version-json-v1"
PROC_SELF_CGROUP = Path("/proc/self/cgroup")
CGROUP_V2_ROOT = Path("/sys/fs/cgroup")


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


def _bounded_regular_bytes(path, label, *, max_bytes=MAX_JSON_BYTES, single_link=True):
    try:
        before = path.lstat()
    except OSError as error:
        raise SystemExit(f"{label} cannot be read before authentic input") from error
    if not stat.S_ISREG(before.st_mode) or (single_link and before.st_nlink != 1):
        qualifier = "single-link " if single_link else ""
        raise SystemExit(f"{label} is not a {qualifier}regular file")
    if before.st_size > max_bytes:
        raise SystemExit(f"{label} exceeds the frozen byte cap")

    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW"):
        flags |= getattr(os, name, 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise SystemExit(f"{label} cannot be read before authentic input") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (single_link and opened.st_nlink != 1):
            qualifier = "single-link " if single_link else ""
            raise SystemExit(f"{label} is not a {qualifier}regular file")
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise SystemExit(f"{label} changed while being opened")
        if opened.st_size > max_bytes:
            raise SystemExit(f"{label} exceeds the frozen byte cap")

        reads = []
        for _ in range(2):
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks = []
            remaining = max_bytes + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            reads.append(b"".join(chunks))
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    try:
        current = path.lstat()
    except OSError as error:
        raise SystemExit(f"{label} changed while being read") from error
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
    )
    if any(getattr(opened, field) != getattr(after, field) for field in stable_fields):
        raise SystemExit(f"{label} changed while being read")
    if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
        raise SystemExit(f"{label} path changed while being read")
    if len(reads[0]) > max_bytes:
        raise SystemExit(f"{label} exceeds the frozen byte cap")
    if reads[0] != reads[1] or len(reads[0]) != after.st_size:
        raise SystemExit(f"{label} changed while being read")
    return reads[0]


def _bounded_pseudo_bytes(path, label, *, max_bytes=MAX_JSON_BYTES):
    """Read a procfs/cgroupfs pseudo-file twice through one stable descriptor."""

    try:
        before = path.lstat()
    except OSError as error:
        raise SystemExit(f"{label} cannot be read") from error
    if not stat.S_ISREG(before.st_mode):
        raise SystemExit(f"{label} is not a regular pseudo-file")
    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW"):
        flags |= getattr(os, name, 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise SystemExit(f"{label} cannot be opened") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise SystemExit(f"{label} is not a regular pseudo-file")
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise SystemExit(f"{label} changed while being opened")
        reads = []
        for _ in range(2):
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks = []
            remaining = max_bytes + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > max_bytes:
                raise SystemExit(f"{label} exceeds the byte cap")
            reads.append(raw)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        current = path.lstat()
    except OSError as error:
        raise SystemExit(f"{label} changed while being read") from error
    stable_fields = ("st_dev", "st_ino", "st_mode", "st_nlink")
    if any(getattr(opened, field) != getattr(after, field) for field in stable_fields):
        raise SystemExit(f"{label} changed while being read")
    if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
        raise SystemExit(f"{label} path changed while being read")
    if reads[0] != reads[1]:
        raise SystemExit(f"{label} changed while being read")
    return reads[0]


def _strict_nonnegative_integer(raw, label):
    try:
        text = raw.decode("ascii").strip()
        value = int(text)
    except (UnicodeDecodeError, ValueError) as error:
        raise SystemExit(f"{label} is not a nonnegative integer") from error
    if value < 0 or str(value) != text:
        raise SystemExit(f"{label} is not a canonical nonnegative integer")
    return value


def _live_cgroup_v2():
    """Bind the current cgroup v2 leaf and recompute tight ancestor headroom."""

    try:
        cgroup_text = _bounded_pseudo_bytes(
            PROC_SELF_CGROUP, "live /proc/self/cgroup"
        ).decode("utf-8")
    except UnicodeDecodeError as error:
        raise SystemExit("live /proc/self/cgroup is not UTF-8") from error
    lines = cgroup_text.splitlines()
    if len(lines) != 1 or not lines[0].startswith("0::"):
        raise SystemExit("live process is not in one cgroup v2 hierarchy")
    relative_text = lines[0][3:]
    relative = Path(relative_text)
    if (
        not relative_text.startswith("/")
        or ".." in relative.parts
        or "\x00" in relative_text
    ):
        raise SystemExit("live cgroup v2 path is invalid")
    try:
        root = CGROUP_V2_ROOT.resolve(strict=True)
        leaf = (root / relative_text.lstrip("/")).resolve(strict=True)
    except OSError as error:
        raise SystemExit("live cgroup v2 leaf cannot be resolved") from error
    if leaf != root and root not in leaf.parents:
        raise SystemExit("live cgroup v2 leaf escapes the hierarchy")
    leaf_stat = leaf.stat()
    if not stat.S_ISDIR(leaf_stat.st_mode):
        raise SystemExit("live cgroup v2 leaf is not a directory")

    finite_headrooms = []
    current = leaf
    while True:
        current_raw = _bounded_pseudo_bytes(
            current / "memory.current", "live cgroup memory.current"
        )
        usage = _strict_nonnegative_integer(
            current_raw, "live cgroup memory.current"
        )
        maximum_raw = _bounded_pseudo_bytes(
            current / "memory.max", "live cgroup memory.max"
        )
        maximum_text = maximum_raw.decode("ascii").strip()
        if maximum_text != "max":
            maximum = _strict_nonnegative_integer(
                maximum_raw, "live cgroup memory.max"
            )
            if usage > maximum:
                raise SystemExit("live cgroup memory.current exceeds memory.max")
            finite_headrooms.append(maximum - usage)
        if current == root:
            break
        current = current.parent
    if not finite_headrooms:
        raise SystemExit("live cgroup hierarchy has no finite memory bound")
    return {
        "relative_path": relative_text,
        "leaf_device": leaf_stat.st_dev,
        "leaf_inode": leaf_stat.st_ino,
        "ancestor_headroom_bytes": min(finite_headrooms),
    }


def _parse_utc(value, field):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SystemExit(f"{field} is not a frozen UTC timestamp")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise SystemExit(f"{field} is not a valid UTC timestamp") from error


def _dependency_manifest_bytes():
    entries = []
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        version = distribution.version
        if (
            not isinstance(name, str)
            or not isinstance(version, str)
            or not name
            or not version
        ):
            raise SystemExit("installed dependency metadata is incomplete")
        entries.append((name, version))
    entries.sort()
    encoded = json.dumps(entries, ensure_ascii=True, separators=(",", ":")) + "\n"
    return encoded.encode()


def _runtime_digests():
    try:
        executable = Path(sys.executable).resolve(strict=True)
    except OSError as error:
        raise SystemExit("runtime Python executable cannot be resolved") from error
    executable_raw = _bounded_regular_bytes(
        executable,
        "runtime Python executable",
        max_bytes=MAX_EXECUTABLE_BYTES,
        single_link=False,
    )
    return {
        "python_executable_sha256": _sha256(executable_raw),
        "dependency_manifest_sha256": _sha256(_dependency_manifest_bytes()),
    }


def _frozen_source_manifest(request):
    raw = _bounded_regular_bytes(SOURCE_FREEZE, "source manifest")
    manifest = _strict_json(raw, "source manifest")
    if manifest.get("identity") != request["identity"]:
        raise SystemExit("source manifest identity mismatch")
    if manifest.get("execution_key") != request["execution_key"]:
        raise SystemExit("source manifest execution key mismatch")
    if manifest.get("status") != "SOURCE_ONLY_RESOURCE_HOLD":
        raise SystemExit("source manifest status mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise SystemExit("source manifest file inventory is not frozen")
    for relative, expected in files.items():
        relative_path = Path(relative)
        if (
            not isinstance(relative, str)
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or not isinstance(expected, str)
            or len(expected) != 64
        ):
            raise SystemExit("source manifest file entry is invalid")
        source_raw = _bounded_regular_bytes(
            REPO / relative_path, f"source file {relative}"
        )
        if _sha256(source_raw) != expected:
            raise SystemExit(
                f"frozen source differs before authentic input: {relative}"
            )
    return _sha256(raw)


def _read_original(request, kind, source_manifest_sha256):
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
        "source_manifest_sha256": source_manifest_sha256,
        "input_sha256": request["input"]["index537_collector_sha256"],
        "host": "desktop",
    }.items():
        if original.get(field) != expected_value:
            raise SystemExit(f"{kind} original {field} mismatch")
    return original


def _validate_originals(request, originals):
    admission = request["runtime_admission"]
    if admission.get("require_live_cgroup_v2") is not True:
        raise SystemExit("live cgroup v2 admission is not required")
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
    live_cgroup = _live_cgroup_v2()
    expected_cgroup = {
        "relative_path": observation.get("cgroup_v2_relative_path"),
        "leaf_device": observation.get("cgroup_v2_leaf_device"),
        "leaf_inode": observation.get("cgroup_v2_leaf_inode"),
    }
    for field in ("leaf_device", "leaf_inode"):
        if not isinstance(expected_cgroup[field], int) or isinstance(
            expected_cgroup[field], bool
        ):
            raise SystemExit(f"observed cgroup v2 {field} is not an integer")
    if expected_cgroup != {
        field: live_cgroup[field] for field in expected_cgroup
    }:
        raise SystemExit("live cgroup v2 identity differs from the observation")
    if live_cgroup["ancestor_headroom_bytes"] < memory_bytes:
        raise SystemExit("live ancestor cgroup headroom is below the allocation")

    runtime = originals["runtime"]
    if not isinstance(runtime.get("runtime_id"), str) or not runtime["runtime_id"]:
        raise SystemExit("runtime identity is not frozen")
    if runtime.get("dependency_manifest_format") != DEPENDENCY_MANIFEST_FORMAT:
        raise SystemExit("runtime dependency manifest format is not frozen")
    current_runtime = _runtime_digests()
    for field in ("python_executable_sha256", "dependency_manifest_sha256"):
        value = runtime.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise SystemExit(f"runtime {field} is not frozen")
        if value != current_runtime[field]:
            raise SystemExit(
                f"runtime {field} does not match the executing environment"
            )
    return {
        "allocation_memory_bytes": memory_bytes,
        "cgroup_v2_relative_path": expected_cgroup["relative_path"],
        "cgroup_v2_leaf_device": expected_cgroup["leaf_device"],
        "cgroup_v2_leaf_inode": expected_cgroup["leaf_inode"],
    }


def revalidate_runtime_cgroup(request):
    """Recheck the admitted cgroup immediately before a lane process starts."""

    expected = request.get("_validated_live_cgroup")
    if not isinstance(expected, dict):
        raise SystemExit("validated live cgroup binding is absent")
    required = {
        "allocation_memory_bytes",
        "cgroup_v2_relative_path",
        "cgroup_v2_leaf_device",
        "cgroup_v2_leaf_inode",
    }
    if set(expected) != required:
        raise SystemExit("validated live cgroup binding is malformed")
    live = _live_cgroup_v2()
    identity = {
        "cgroup_v2_relative_path": live["relative_path"],
        "cgroup_v2_leaf_device": live["leaf_device"],
        "cgroup_v2_leaf_inode": live["leaf_inode"],
    }
    if identity != {field: expected[field] for field in identity}:
        raise SystemExit("live cgroup v2 identity changed before lane spawn")
    if live["ancestor_headroom_bytes"] < expected["allocation_memory_bytes"]:
        raise SystemExit("live ancestor cgroup headroom fell before lane spawn")
    return live


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
    source_manifest_sha256 = _frozen_source_manifest(request)
    originals = {
        kind: _read_original(request, kind, source_manifest_sha256)
        for kind in ORIGINAL_SCHEMAS
    }
    request["_validated_live_cgroup"] = _validate_originals(request, originals)
    return request
