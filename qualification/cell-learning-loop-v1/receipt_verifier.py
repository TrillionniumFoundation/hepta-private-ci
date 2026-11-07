"""Verify saved phase receipts against their original captured worker output.

These are local consistency checks, not an authenticated writer or an adoption
gate. A failed or unverifiable attempt never becomes permission to run it again.
"""

import hashlib
import json
import math
from pathlib import Path
import re

from loop_common import canonical, identity


MAX_RECEIPT_BYTES = 512000
PARENT_FIELDS = {"parent_observed", "protocol_sha256"}


def decode_receipt(raw):
    """Decode one unambiguous JSON object, preserving bool/int distinctions."""
    def unique_fields(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate receipt field: " + key)
            value[key] = item
        return value

    def invalid_constant(value):
        raise ValueError("non-finite receipt number: " + value)

    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError("receipt exceeds the repository blob bound")
    try:
        value = json.loads(raw, object_pairs_hook=unique_fields,
                           parse_constant=invalid_constant)
        canonical(value)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid worker receipt: " + str(error)) from error
    if type(value) is not dict:
        raise ValueError("worker receipt must be a JSON object")
    return value


def read_capture(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or linked receipt/capture: " + path.name)
    with path.open("rb") as stream:
        raw = stream.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError("receipt/capture exceeds the repository blob bound: " + path.name)
    return raw


def nonnegative_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def verify_completed_receipt(run, phase, receipt):
    """Require a completed, exact phase/protocol/output/process binding."""
    if (not re.fullmatch(r"[a-z][a-z_]*", phase) or type(receipt) is not dict
            or receipt.get("status") != "completed" or receipt.get("phase") != phase
            or type(receipt.get("result")) is not dict
            or receipt["result"].get("engineering_passed") is not True):
        raise ValueError("phase did not complete successfully")
    observed = receipt.get("parent_observed")
    if (type(observed) is not dict or type(observed.get("returncode")) is not int
            or observed["returncode"] != 0):
        raise ValueError("parent did not observe an integer zero exit code")
    if receipt.get("protocol_sha256") != identity(run / "PROTOCOL.json")["sha256"]:
        raise ValueError("receipt belongs to a different frozen protocol")
    for directory in (run / "phase_results", run / "attempts", run / "attempts" / phase):
        if directory.is_symlink():
            raise ValueError("linked phase evidence directory")
    captures = {}
    for name in ("stdout", "stderr"):
        raw = read_capture(run / "attempts" / phase / (name + ".txt"))
        actual = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        if canonical(observed.get(name)) != canonical(actual):
            raise ValueError("captured " + name + " differs from the parent receipt")
        captures[name] = raw
    worker = decode_receipt(captures["stdout"])
    recorded_worker = {key: value for key, value in receipt.items() if key not in PARENT_FIELDS}
    if PARENT_FIELDS.intersection(worker) or canonical(worker) != canonical(recorded_worker):
        raise ValueError("saved worker result differs from original stdout")
    instance = worker.get("process_instance_id")
    if (type(worker.get("pid")) is not int or worker["pid"] <= 0
            or type(instance) is not str or not re.fullmatch(r"[0-9a-f]{32}", instance)):
        raise ValueError("worker process identity is missing or invalid")
    metrics = worker.get("worker_metrics")
    if (type(metrics) is not dict or type(metrics.get("peak_rss_bytes")) is not int
            or metrics["peak_rss_bytes"] <= 0
            or any(not nonnegative_number(values.get(key))
                   for values in (observed, metrics)
                   for key in ("wall_seconds", "cpu_user_seconds", "cpu_system_seconds"))):
        raise ValueError("phase process measurements are missing or invalid")
