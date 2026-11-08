"""Reconcile nested host/actor observations on one Linux monotonic clock.

This is an observer, not a Cell authenticator. Only explicit, disjoint spans
receive a category. Process launch/import/waiting gaps stay UNKNOWN. Child CPU
is never subtracted from a wall clock or presumed covered by parent CPU.
"""

import os
import re
import stat

from .span_meter import CATEGORIES, MeterError, record_from_jsonl, verify_record


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
    by_id = {}
    for receipt in returned:
        replay = replay_receipt(receipt)
        meter_id = replay["header"]["meter_id"]
        if meter_id in by_id:
            raise MeterError("DUPLICATE_RETURNED_ACTOR_METER")
        by_id[meter_id] = receipt
    paths = sorted(output_directory.glob("decision-*.meter.jsonl"))
    if len(paths) > 8:
        raise MeterError("ACTOR_JOURNAL_INVENTORY_EXCEEDS_BOUND")
    journals = set()
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
        suffix = replay["header"]["operation_id"].rsplit("/decision/", 1)[-1]
        if not re.fullmatch(r"0[0-7]", suffix) or path.name != f"decision-{suffix}.meter.jsonl":
            raise MeterError("ACTOR_JOURNAL_OPERATION_FILENAME_MISMATCH")
        if key in by_id:
            if by_id[key]["raw_spans_sha256"] != replay["record_sha256"]:
                raise MeterError("ACTOR_JOURNAL_RECEIPT_MISMATCH")
        else:
            by_id[key] = {"raw_spans": record, "raw_spans_sha256": replay["record_sha256"]}
    if set(by_id) != journals:
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
