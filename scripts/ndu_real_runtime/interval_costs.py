"""Reconcile nested host/actor observations on one Linux monotonic clock.

This is an observer, not a Cell authenticator. Only explicit, disjoint spans
receive a category. Process launch/import/waiting gaps stay UNKNOWN. Child CPU
is never subtracted from a wall clock or presumed covered by parent CPU.
"""

import os
import re
import stat
import time

from .span_meter import CATEGORIES, MeterError, record_from_jsonl, record_sha256, verify_record


def replay_receipt(receipt):
    replay = verify_record(receipt["raw_spans"], expected_sha256=receipt["raw_spans_sha256"])
    if not replay["valid"]:
        raise MeterError("INVALID_RAW_SPANS: " + repr(replay["diagnostics"]))
    return replay


def exclusive_intervals(replay, *, excluded_ids=()):
    """Return explicit span intervals after removing direct nested children."""
    nodes = {node["span_id"]: node for node in replay["spans"]}
    through = replay["observed_through_monotonic_ns"]
    result = []
    for node in nodes.values():
        if node["category"] is None or node["span_id"] in excluded_ids:
            continue
        cursor = node["start_monotonic_ns"]
        end = node["end_monotonic_ns"] if node["end_monotonic_ns"] is not None else through
        for child_id in node["children"]:
            child = nodes[child_id]
            start = child["start_monotonic_ns"]
            if cursor < start:
                result.append((cursor, start, node["category"]))
            cursor = child["end_monotonic_ns"] if child["end_monotonic_ns"] is not None else through
        if cursor < end:
            result.append((cursor, end, node["category"]))
    return result


def actor_receipts(returned, output_directory):
    """Recover each durable actor prefix, including a killed original attempt.

    Returned observations and their on-disk journals must agree byte-for-byte
    as records. A final truncated journal is retained and rejected, not repaired.
    """
    returned_by_operation, by_id = {}, {}
    for receipt in returned:
        operation = receipt.get("operation_id")
        digest = receipt.get("raw_spans_sha256")
        if not isinstance(operation, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise MeterError("INVALID_RETURNED_ACTOR_RECEIPT")
        if "raw_spans" in receipt:
            replay = replay_receipt(receipt)
            if replay["header"]["operation_id"] != operation:
                raise MeterError("RETURNED_ACTOR_OPERATION_MISMATCH")
        elif receipt.get("span_transport") != "sha256_bound_create_only_journal":
            raise MeterError("UNKNOWN_ACTOR_SPAN_TRANSPORT")
        if operation in returned_by_operation:
            raise MeterError("DUPLICATE_RETURNED_ACTOR_METER")
        returned_by_operation[operation] = receipt
    paths = sorted(output_directory.glob("decision-*.meter.jsonl"))
    if len(paths) > 8:
        raise MeterError("ACTOR_JOURNAL_INVENTORY_EXCEEDS_BOUND")
    journals, observed_operations = set(), set()
    for path in paths:
        if path.is_symlink():
            raise MeterError("SYMLINK_ACTOR_JOURNAL")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > 4 * 1024 * 1024:
                raise MeterError("INVALID_ACTOR_JOURNAL_FILE")
            raw = stream.read(4 * 1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        named = path.lstat()
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                                  value.st_mtime_ns, value.st_ctime_ns)
        if (len(raw) > 4 * 1024 * 1024 or identity(before) != identity(after)
                or identity(after) != identity(named)):
            raise MeterError("ACTOR_JOURNAL_CHANGED_DURING_READ")
        record = record_from_jsonl(raw)
        replay = verify_record(record)
        if not replay["valid"]:
            raise MeterError("INVALID_ACTOR_JOURNAL: " + repr(replay["diagnostics"]))
        key = replay["header"]["meter_id"]
        if key in journals:
            raise MeterError("DUPLICATE_ACTOR_JOURNAL")
        journals.add(key)
        operation = replay["header"]["operation_id"]
        if operation in observed_operations:
            raise MeterError("DUPLICATE_ACTOR_JOURNAL_OPERATION")
        observed_operations.add(operation)
        suffix = operation.rsplit("/decision/", 1)[-1]
        if not re.fullmatch(r"0[0-7]", suffix) or path.name != f"decision-{suffix}.meter.jsonl":
            raise MeterError("ACTOR_JOURNAL_OPERATION_FILENAME_MISMATCH")
        if operation in returned_by_operation:
            receipt = returned_by_operation[operation]
            if receipt["raw_spans_sha256"] != replay["record_sha256"]:
                raise MeterError("ACTOR_JOURNAL_RECEIPT_MISMATCH")
            if (not replay["complete_record"]
                    or receipt.get("wall_seconds") != replay["envelope"]["inclusive_wall_ns"] / 1e9
                    or receipt.get("cpu_seconds") != replay["envelope"]["inclusive_process_cpu_ns"] / 1e9
                    or receipt.get("costs") != {key: replay["categories"][key]["exclusive_wall_ns"] / 1e9 for key in CATEGORIES}):
                raise MeterError("ACTOR_SUMMARY_DIFFERS_FROM_RAW_JOURNAL")
            by_id[key] = {**receipt, "raw_spans": record}
        else:
            by_id[key] = {"raw_spans": record, "raw_spans_sha256": replay["record_sha256"]}
    if not set(returned_by_operation) <= observed_operations:
        raise MeterError("MISSING_RETURNED_ACTOR_JOURNAL")
    return list(by_id.values())


def reconcile(host, actors, *, lifetime_name="mandatory isolated actor lifetime"):
    """Overlay actual actor intervals; reject overlaps instead of scalar clipping."""
    parent = replay_receipt(host)
    if not parent["complete_record"]:
        raise MeterError("INCOMPLETE_HOST_ENVELOPE")
    matches = [row["attempt_id"] for row in host["stages"] if row["name"] == lifetime_name]
    if len(matches) != 1:
        raise MeterError("AMBIGUOUS_ACTOR_LIFETIME")
    lifetimes = [node for node in parent["spans"] if node["span_id"] == matches[0]]
    if len(lifetimes) != 1:
        raise MeterError("MISSING_ACTOR_LIFETIME_SPAN")
    lifetime = lifetimes[0]
    intervals = exclusive_intervals(parent, excluded_ids=matches)
    seen, operations, envelopes, children = set(), set(), [], []
    for receipt in actors:
        child = replay_receipt(receipt)
        header, envelope = child["header"], child["envelope"]
        prefix = parent["header"]["operation_id"] + "/decision/"
        if not header["operation_id"].startswith(prefix) or not re.fullmatch(r"0[0-7]", header["operation_id"][len(prefix):]):
            raise MeterError("UNBOUND_ACTOR_OPERATION")
        if header["operation_id"] in operations:
            raise MeterError("DUPLICATE_ACTOR_OPERATION")
        operations.add(header["operation_id"])
        if header["meter_id"] in seen or header["process_id"] == parent["header"]["process_id"]:
            raise MeterError("DUPLICATE_OR_HOST_ACTOR_IDENTITY")
        if children and any(header[key] != children[0]["header"][key] for key in ("process_id", "process_instance_id")):
            raise MeterError("MULTIPLE_ACTOR_PROCESSES")
        seen.add(header["meter_id"])
        start = envelope["start_monotonic_ns"]
        end = envelope["end_monotonic_ns"] if envelope["end_monotonic_ns"] is not None else child["observed_through_monotonic_ns"]
        if not lifetime["start_monotonic_ns"] <= start <= end <= lifetime["end_monotonic_ns"]:
            raise MeterError("ACTOR_OUTSIDE_HOST_LIFETIME")
        envelopes.append((start, end))
        intervals.extend(exclusive_intervals(child))
        children.append(child)
    envelopes.sort()
    if any(left[1] > right[0] for left, right in zip(envelopes, envelopes[1:])):
        raise MeterError("OVERLAPPING_ACTOR_ENVELOPES")
    intervals.sort()
    if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
        raise MeterError("OVERLAPPING_CLASSIFIED_INTERVALS")
    categories = {key: 0 for key in CATEGORIES}
    for start, end, category in intervals:
        categories[category] += end - start
    envelope = parent["envelope"]
    unknown = envelope["inclusive_wall_ns"] - sum(categories.values())
    if unknown < 0:
        raise MeterError("CLASSIFIED_INTERVALS_EXCEED_ENVELOPE")
    return {**host, "costs": {key: value / 1e9 for key, value in categories.items()},
            "observed_unclassified_overhead_seconds": unknown / 1e9,
            "cpu_seconds": (envelope["inclusive_process_cpu_ns"] + sum(
                child["envelope"]["inclusive_process_cpu_ns"] for child in children)) / 1e9,
            "cpu_scope": "observed_host_and_actor_processes; child startup and OCR subprocess CPU not included",
            "child_process_cpu_seconds": None,
            "unclosed_actor_subcategories": lifetime["status"] != "SUCCEEDED" or any(
                not child["complete_record"] for child in children),
            "actor_record_sha256s": [child["record_sha256"] for child in children],
            "actor_observed_prefixes": len(children),
            "interval_reconciliation": "EXACT_MONOTONIC_INTERVALS_SAME_HOST",
            "subcategory_status": "OBSERVED_LOWER_BOUNDS; startup, waiting and uninstrumented work are UNKNOWN",
            "subcategory_upper_bounds": {key: None for key in CATEGORIES}}


def close_observer_tail(receipt):
    """Charge actual journal replay/accounting work after the host span closed.

    Call once after reconciliation, before scoring. Final result serialization
    remains outside this endpoint and inside the outer original-attempt meter.
    This observation is an unsigned same-process clock record, not authority.
    """
    if "observer_tail" in receipt:
        raise MeterError("OBSERVER_TAIL_ALREADY_RECORDED")
    header, last = receipt["raw_spans"]["header"], receipt["raw_spans"]["events"][-1]
    if (header["process_id"] != os.getpid() or last.get("kind") != "close"
            or last.get("span_id") != "envelope"):
        raise MeterError("INVALID_OBSERVER_TAIL_ORIGIN")
    wall_end, cpu_end = time.monotonic_ns(), time.process_time_ns()
    tail = {"schema": "ndu.real.observer-tail.v1", "process_id": os.getpid(),
            "parent_record_sha256": receipt["raw_spans_sha256"],
            "start_monotonic_ns": last["monotonic_ns"], "end_monotonic_ns": wall_end,
            "start_process_time_ns": last["process_time_ns"], "end_process_time_ns": cpu_end,
            "category": "UNKNOWN", "cpu_scope": "emitting_process_excluding_children"}
    wall, cpu = wall_end - last["monotonic_ns"], cpu_end - last["process_time_ns"]
    if min(wall, cpu) < 0:
        raise MeterError("OBSERVER_TAIL_CLOCK_REGRESSION")
    return {**receipt, "observer_tail": tail, "observer_tail_sha256": record_sha256(tail),
            "wall_seconds": receipt["wall_seconds"] + wall / 1e9,
            "cpu_seconds": receipt["cpu_seconds"] + cpu / 1e9,
            "observed_unclassified_overhead_seconds": receipt["observed_unclassified_overhead_seconds"] + wall / 1e9,
            "deployment_latency_scope": "host execution plus journal replay/accounting; final serialization in outer task only"}
