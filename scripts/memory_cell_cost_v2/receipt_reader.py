"""Normalize known raw process receipts; unknown meters stay null, failures cost."""

from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path


def ns(seconds):
    if seconds is None:
        return None
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("finite nonnegative measured seconds required")
    return int(Decimal(str(seconds)) * 1_000_000_000)


def read_receipt(path, *, format_name, attempt_id, role="charge", parent_id=None):
    if role not in ("charge", "attribution") or (role == "attribution") != (
        parent_id is not None
    ):
        raise ValueError("nested attribution needs a charged parent")
    path = Path(path)
    raw = path.read_bytes()
    value = json.loads(raw)
    if format_name == "procedural-v1":
        cpu = ns(value.get("cpu_seconds"))
        output_bytes = 0
        for name in ("stdout", "stderr"):
            data = (path.parent / (name + ".log")).read_bytes()
            if hashlib.sha256(data).hexdigest() != value[name + "_sha256"]:
                raise ValueError("raw stream differs from process receipt")
            output_bytes += len(data)
    elif format_name == "wait4-v2":
        usage = value.get("usage")
        cpu = (
            None
            if usage is None
            else ns(usage["user_cpu_seconds"]) + ns(usage["system_cpu_seconds"])
        )
        streams = [value.get(name, {}).get("bytes") for name in ("stdout", "stderr")]
        output_bytes = None if None in streams else sum(streams)
        for name in ("stdout", "stderr"):
            recorded = value.get(name, {})
            if "sha256" in recorded:
                data = (path.parent / name).read_bytes()
                if (
                    len(data) != recorded["bytes"]
                    or hashlib.sha256(data).hexdigest() != recorded["sha256"]
                ):
                    raise ValueError("raw stream differs from process receipt")
    else:
        raise ValueError("unregistered receipt schema; do not infer unknown costs")
    rc = value.get("returncode")
    if rc is not None and type(rc) is not int:
        raise ValueError("invalid returncode")
    failed = rc != 0 or any(
        value.get(k) for k in ("error", "timeout", "cleanup_error", "reap_error")
    )
    return {
        "attempt_id": attempt_id,
        "role": role,
        "parent_id": parent_id,
        "path": str(path),
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "returncode": rc,
        "failed": failed,
        "cpu_ns": cpu,
        "wall_ns": ns(value.get("wall_seconds")),
        "output_bytes": output_bytes,
        "input_tokens": None,
        "output_tokens": None,
        "whole_host_cpu_ns": None,
        "energy_joules": None,
        "billing_usd": None,
    }


def total(receipts):
    ids, identities = set(), set()
    for row in receipts:
        if row["attempt_id"] in ids or row["receipt_sha256"] in identities:
            raise ValueError("duplicate attempt or receipt would double-charge work")
        ids.add(row["attempt_id"])
        identities.add(row["receipt_sha256"])
    charged = [r for r in receipts if r["role"] == "charge"]
    charged_ids = {r["attempt_id"] for r in charged}
    if any(
        r["parent_id"] not in charged_ids
        for r in receipts
        if r["role"] == "attribution"
    ):
        raise ValueError("attribution parent absent")
    dimensions = {}
    for key in ("cpu_ns", "wall_ns", "output_bytes", "input_tokens", "output_tokens"):
        known = [r[key] for r in charged if r[key] is not None]
        dimensions[key] = {
            "total": sum(known) if len(known) == len(charged) else None,
            "known_subtotal": sum(known),
            "unknown_attempts": len(charged) - len(known),
        }
    return {
        "charged_attempts": len(charged),
        "failed_attempts": sum(r["failed"] for r in charged),
        "attribution_only_attempts": len(receipts) - len(charged),
        "dimensions": dimensions,
        "whole_host_cpu_ns": None,
        "energy_joules": None,
        "billing_usd": None,
    }


def load_summary(samples, planned_measured):
    """Nearest-rank percentiles retain failures; a failed attempt is not a success."""
    keys = [(r["phase"], r["index"]) for r in samples]
    if len(keys) != len(set(keys)) or any(
        r["phase"] not in ("warmup", "measured") for r in samples
    ):
        raise ValueError("unique registered sample identities required")
    rows = [r for r in samples if r["phase"] == "measured"]
    if (
        type(planned_measured) is not int
        or planned_measured < len(rows)
        or planned_measured < 1
    ):
        raise ValueError("planned denominator must retain unattempted work")
    for row in samples:
        if any(
            type(row[k]) is not int or row[k] < 0
            for k in ("wall_ns", "cpu_ns", "start_ns", "end_ns")
        ):
            raise ValueError("invalid measured sample")
        if (
            row["end_ns"] - row["start_ns"] != row["wall_ns"]
            or type(row["success"]) is not bool
        ):
            raise ValueError("inconsistent sample duration or outcome")
    durations = sorted(r["wall_ns"] for r in rows)

    def percentile(q):
        return durations[math.ceil(q * len(durations)) - 1] if durations else None

    interval = (
        max(r["end_ns"] for r in rows) - min(r["start_ns"] for r in rows) if rows else 0
    )
    successes = sum(r["success"] for r in rows)
    return {
        "planned_measured": planned_measured,
        "attempted": len(rows),
        "successful": successes,
        "failed": len(rows) - successes,
        "unattempted": planned_measured - len(rows),
        "p50_all_attempts_ns": percentile(0.5),
        "p95_all_attempts_ns": percentile(0.95),
        "percentile_method": "nearest-rank; tiny descriptive sample, no tail SLA claim",
        "measurement_interval_ns": interval,
        "successful_queries_per_second": successes * 1_000_000_000 / interval
        if interval
        else None,
        "warmup_attempts_separate": sum(r["phase"] == "warmup" for r in samples),
    }
