"""Disjoint observed stage costs, including failures and unclassified overhead.

This observer does not replace the native Cell journal. Its records are inputs
for native inventory reconciliation. Wall seconds are measured latency; they
are not a monetary or energy conversion. Unknown charge/energy stay null.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import time

CATEGORIES = ("encoder", "shared", "decoder", "critic", "planning", "codec", "failure", "retry", "sync")


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path, value):
    """Create once; the native owner remains responsible for authoritative commit."""
    path = Path(path)
    temporary = path.with_name(path.name + f".{os.getpid()}.partial")
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return hashlib.sha256(raw).hexdigest()


def _usage():
    own = resource.getrusage(resource.RUSAGE_SELF)
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + child.ru_utime + child.ru_stime


class Meter:
    def __init__(self, operation_id, *, native_attempt_callback=None):
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Original operation identity is required")
        self.operation_id = operation_id
        self.rows, self.stack = [], []
        self.start_ns, self.start_cpu = time.perf_counter_ns(), _usage()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.callback = native_attempt_callback
        self.closed = False

    @contextmanager
    def stage(self, category, name, *, retry_of=None):
        if self.closed or category not in CATEGORIES or not name:
            raise ValueError("Invalid stage or closed meter")
        index = len(self.rows)
        row = {"attempt_id": f"{self.operation_id}/stage/{index:06d}", "category": category,
               "name": name, "retry_of": retry_of, "status": "started",
               "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
               "wall_seconds": None, "cpu_seconds": None, "child_wall_ns": 0, "child_cpu": 0.0}
        if retry_of is not None and not any(x["attempt_id"] == retry_of for x in self.rows):
            raise ValueError("Retry predecessor is absent from the observed inventory")
        self.rows.append(row)
        wall, cpu = time.perf_counter_ns(), _usage()
        self.stack.append(row)
        try:
            if self.callback is not None:
                self.callback("start", dict(row))
            yield row
            row["status"] = "success"
        except BaseException as error:
            row["status"] = "failed"
            row["error_type"] = type(error).__name__
            raise
        finally:
            inclusive_ns, inclusive_cpu = time.perf_counter_ns() - wall, _usage() - cpu
            if self.stack.pop() is not row:
                raise RuntimeError("Non-LIFO meter use")
            row["wall_seconds"] = (inclusive_ns - row.pop("child_wall_ns")) / 1e9
            row["cpu_seconds"] = max(0.0, inclusive_cpu - row.pop("child_cpu"))
            row["finished_at"] = datetime.now(timezone.utc).isoformat()
            if self.stack:
                self.stack[-1]["child_wall_ns"] += inclusive_ns
                self.stack[-1]["child_cpu"] += inclusive_cpu
            if self.callback is not None:
                try:
                    self.callback("finish", dict(row))
                except BaseException as error:
                    row["publication_error_type"] = type(error).__name__
                    if row["status"] == "success":
                        row["status"] = "publication_failed"
                        raise

    def finish(self):
        if self.closed or self.stack:
            raise ValueError("Meter already closed or has an active stage")
        self.closed = True
        wall, cpu = (time.perf_counter_ns() - self.start_ns) / 1e9, _usage() - self.start_cpu
        costs = {name: sum(row["wall_seconds"] for row in self.rows if row["category"] == name)
                 for name in CATEGORIES}
        known = sum(costs.values())
        if known > wall + 1e-6:
            raise RuntimeError("Exclusive stage wall time exceeds the original operation")
        # Measured owner/serialization gaps are synchronization overhead, never
        # discarded. Zero in an unused category means observed no activity.
        gap = max(0.0, wall - known)
        costs["sync"] += gap
        return {"schema": "ndu-real-exclusive-meter-v1", "operation_id": self.operation_id,
                "started_at": self.started_at, "finished_at": datetime.now(timezone.utc).isoformat(),
                "wall_seconds": wall, "cpu_seconds": cpu, "cost_unit": "observed_wall_second",
                "costs": costs, "observed_unclassified_overhead_seconds": gap,
                "stages": self.rows, "energy_joules": None, "provider_charges": None,
                "native_owner_inventory_verified": False, "full_physical_cost_complete": False,
                "scientific_admission": "HOLD"}
