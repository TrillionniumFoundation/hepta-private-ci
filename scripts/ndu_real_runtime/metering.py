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

from .span_meter import CATEGORIES, SpanMeter, verify_record



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


def transport_receipt(receipt):
    """Send bounded summary metadata; the raw journal remains independently bound."""
    if receipt.get("schema") != "ndu-real-exclusive-meter-v2":
        raise ValueError("Compact transport requires a v2 receipt")
    return {**{key: value for key, value in receipt.items() if key not in {"raw_spans", "stages"}},
            "span_transport": "sha256_bound_create_only_journal"}


class Meter:
    """Runtime adapter for raw v2 spans; gaps and child CPU remain explicit."""

    def __init__(self, operation_id, *, native_attempt_callback=None, journal_path=None):
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Original operation identity is required")
        self.operation_id = operation_id
        self.rows, self.stack = [], []
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.callback = native_attempt_callback
        self.closed = False
        self.journal = None if journal_path is None else Path(journal_path).open("xb", buffering=0)
        if self.journal is not None:
            descriptor = os.open(Path(journal_path).parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        self.observer = SpanMeter(operation_id, event_sink=self._persist if self.journal else None)

    def _persist(self, raw):
        if self.journal.write(raw) != len(raw):
            raise OSError("Partial event journal write; retain the original file")
        os.fsync(self.journal.fileno())

    @contextmanager
    def stage(self, category, name, *, retry_of=None):
        if self.closed or category not in CATEGORIES or not name:
            raise ValueError("Invalid stage or closed meter")
        index = len(self.rows)
        row = {"attempt_id": f"{self.operation_id}/stage/{index:06d}", "category": category,
               "name": name, "retry_of": retry_of, "status": "started",
               "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
               "wall_seconds": None, "cpu_seconds": None}
        if retry_of is not None and not any(x["attempt_id"] == retry_of for x in self.rows):
            raise ValueError("Retry predecessor is absent from the observed inventory")
        self.rows.append(row)
        self.stack.append(row)
        try:
            with self.observer.span(row["attempt_id"], category):
                if self.callback is not None:
                    self.callback("start", dict(row))
                yield row
                row["status"] = "success"
        except BaseException as error:
            row["status"] = "canceled" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
            row["error_type"] = type(error).__name__
            raise
        finally:
            if self.stack.pop() is not row:
                raise RuntimeError("Non-LIFO meter use")
            row["finished_at"] = datetime.now(timezone.utc).isoformat()
            if self.callback is not None:
                try:
                    replay = verify_record(self.observer.snapshot())
                    if not replay["valid"]:
                        raise ValueError("Invalid spans before native callback")
                    observed = next(span for span in replay["spans"] if span["span_id"] == row["attempt_id"])
                    row.update(wall_seconds=observed["exclusive_wall_ns"] / 1e9,
                               cpu_seconds=observed["exclusive_process_cpu_ns"] / 1e9)
                    self.callback("finish", dict(row))
                except BaseException as error:
                    row["publication_error_type"] = type(error).__name__
                    if row["status"] == "success":
                        row["status"] = "publication_failed"
                        raise

    def finish(self, status=None):
        if self.closed or self.stack:
            raise ValueError("Meter already closed or has an active stage")
        self.closed = True
        status = status or ("FAILED" if any(row["status"] != "success" for row in self.rows) else "SUCCEEDED")
        try:
            raw = self.observer.finish(status)
        finally:
            if self.journal is not None:
                self.journal.close()
        replay = verify_record(raw)
        if not replay["valid"] or not replay["complete_record"]:
            raise ValueError("Invalid original metering events: " + repr(replay["diagnostics"]))
        spans = {span["span_id"]: span for span in replay["spans"]}
        for row in self.rows:
            observed = spans[row["attempt_id"]]
            row.update(wall_seconds=observed["exclusive_wall_ns"] / 1e9,
                       cpu_seconds=observed["exclusive_process_cpu_ns"] / 1e9)
        envelope = replay["envelope"]
        return {"schema": "ndu-real-exclusive-meter-v2", "operation_id": self.operation_id,
                "started_at": self.started_at, "finished_at": datetime.now(timezone.utc).isoformat(),
                "wall_seconds": envelope["inclusive_wall_ns"] / 1e9,
                "cpu_seconds": envelope["inclusive_process_cpu_ns"] / 1e9,
                "cpu_scope": replay["cpu_scope"], "child_process_cpu_seconds": None,
                "cost_unit": "observed_wall_second",
                "costs": {key: replay["categories"][key]["exclusive_wall_ns"] / 1e9 for key in CATEGORIES},
                "observed_unclassified_overhead_seconds": replay["uninstrumented"]["wall_ns"] / 1e9,
                "subcategory_status": "OBSERVED_LOWER_BOUNDS; uninstrumented time is UNKNOWN",
                "subcategory_upper_bounds": {key: None for key in CATEGORIES},
                "raw_spans": raw, "raw_spans_sha256": replay["record_sha256"],
                "stages": self.rows, "energy_joules": None, "provider_charges": None,
                "native_owner_inventory_verified": False, "full_physical_cost_complete": False,
                "scientific_admission": "HOLD"}
