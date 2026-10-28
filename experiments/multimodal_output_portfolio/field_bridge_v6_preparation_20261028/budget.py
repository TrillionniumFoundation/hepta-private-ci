"""Byte accounting from the actual envelope serializer; never starts a study."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from experiments.multimodal_output_portfolio.field_bridge_v6_preparation_20261028.codec import loads, measure, require

MIB = 1024 ** 2
MIN_AVAILABLE = 2 * 1024 ** 3
RAW_CAP = 500 * MIB
REQUIRED_CLASSES = {
    "bank_parent_state": 144, "branch_terminal_state": 576, "bank_prefix_terminal_state": 24,
    "rollout_terminal_state": 36, "parent_probe_output": 144, "branch_probe_output": 576,
    "endpoint_output": 78, "heads": 6, "traces_features_bindings": 1,
}


def measured_envelope(path, maximum_bytes=RAW_CAP):
    require(type(maximum_bytes) is int and 0 <= maximum_bytes <= RAW_CAP, "Measurement cap must be a finite integer within the raw cap")
    require(Path(path).is_file() and Path(path).stat().st_size <= maximum_bytes, "Sample exceeds its artifact cap or is not a regular file")
    with Path(path).open("rb") as stream:
        raw = stream.read(maximum_bytes + 1)
    require(len(raw) <= maximum_bytes, "Sample grew beyond its artifact cap")
    identity = {"path": str(Path(path).resolve()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    restored = loads(raw, identity["sha256"], len(raw))
    measured = measure(restored)
    require(measured["file_bytes"] == len(raw), "Serializer measurement differs from actual file")
    return {**identity, "measurement": measured, "basis": "actual_serialized_envelope"}


def estimate(rows, *, retained_failed_archive_bytes=0, buffer_bytes=8 * MIB, directory_inode_bound=4096):
    """Every missing unit is unknown, never zero; caps do not claim real-data sizing."""
    require(len({r["kind"] for r in rows}) == len(rows), "Duplicate artifact class")
    known, count, largest, missing, units = 0, 0, 0, [], {}
    indexed = {row["kind"]: row for row in rows}
    require(not (set(indexed) - set(REQUIRED_CLASSES)), "Unknown artifact class")
    for kind, expected_count in REQUIRED_CLASSES.items():
        row = indexed.get(kind)
        if row is not None:
            require(type(row["count"]) is int and row["count"] == expected_count, "Artifact count differs or is not an integer")
        if row is None or row.get("unit_bound_bytes") is None:
            missing.append(kind)
            continue
        bound = row["unit_bound_bytes"]
        require(type(bound) is int and bound > 0, "Artifact bound differs")
        require(row["basis"] in ("actual_envelope_with_declared_shape_bound", "declared_artifact_cap"), "Missing sizing basis")
        if row["basis"] == "actual_envelope_with_declared_shape_bound":
            require(type(row.get("envelope_path")) is str and row["envelope_path"], "Actual sizing requires an existing envelope path")
            units[kind] = measured_envelope(row["envelope_path"], min(bound, RAW_CAP))
            measured = units[kind]["bytes"]
            require("measured_bytes" not in row or (type(row["measured_bytes"]) is int and row["measured_bytes"] == measured),
                    "Supplied measurement differs from the actual envelope")
            require(bound >= measured
                    and row.get("shape_bound_verified") is True, "Measured sample is not a complete shape bound")
        known += expected_count * bound
        count += expected_count
        largest = max(largest, bound)
    require(all(type(v) is int and v >= 0 for v in (retained_failed_archive_bytes, buffer_bytes, directory_inode_bound)), "Invalid preservation allowance")
    # An interrupted exclusive write may coexist with every prior successful file.
    failure_reserve = largest + 65536 if not missing else None
    raw_bound = known + failure_reserve if not missing else None
    # No compression saving is assumed. This is an enforced archive writer cap,
    # not a promise that an as-yet nonexistent scientific archive will fit.
    archive_cap = RAW_CAP + 10 * MIB
    peak = (2 * raw_bound + archive_cap + retained_failed_archive_bytes + buffer_bytes) if raw_bound is not None else None
    required_space = max(MIN_AVAILABLE, peak + 256 * MIB) if peak is not None else None
    return {"status": "NOT_REGISTERED / NOT_EXECUTED", "scientific_evidence": False,
        "research_start_permitted": False, "historical_scientific_status": "FAIL", "admission": False,
        "unit_profiles_complete": not missing, "missing_artifact_bounds": missing,
        "actual_measured_units": units,
        "known_planned_payload_bytes": known, "failure_partial_and_receipt_reserve_bytes": failure_reserve,
        "raw_with_failure_bound_bytes": raw_bound, "raw_cap_bytes": RAW_CAP,
        "raw_cap_passed": raw_bound is not None and raw_bound <= RAW_CAP,
        "archive_writer_cap_bytes": archive_cap, "retained_failed_archives_bytes": retained_failed_archive_bytes,
        "full_literal_restore_reserve_bytes": raw_bound, "buffer_bytes": buffer_bytes,
        "peak_new_bytes_before_free_reserve": peak, "free_reserve_bytes": 256 * MIB,
        "minimum_f_bavail_bytes": MIN_AVAILABLE, "required_f_bavail_bytes": required_space,
        "planned_regular_artifacts": count if not missing else None,
        "required_free_inodes": 2 * count + directory_inode_bound + 32 if not missing else None,
        "failure_rule": "Retain partial files and all adverse results. An archive retry adds its retained predecessor bytes; no overwrite or silent deletion.",
        "limits": "Real unit shapes, output serializers, trace caps and directory inventory still require independent registration review; a small synthetic sample is not their bound."}


def disk_gate(path, plan, stat=None):
    if stat is None:
        require(hasattr(os, "statvfs"), "This execution capacity gate requires statvfs; no fallback bypass")
        stat = os.statvfs(path)
    available = stat.f_bavail * stat.f_frsize
    inode_available = stat.f_favail
    passed = (plan["unit_profiles_complete"] and plan["raw_cap_passed"]
              and available >= plan["required_f_bavail_bytes"] and inode_available >= plan["required_free_inodes"])
    return {"path": str(path), "f_bavail_bytes": available, "f_bfree_bytes": stat.f_bfree * stat.f_frsize,
            "free_inodes": inode_available, "basis": "f_bavail for every UID, including root", "capacity_passed": bool(passed),
            "research_start_permitted": False, "registration_still_required": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--filesystem", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    requested = json.loads(args.plan.read_text())
    rows = requested["artifacts"]
    plan = estimate(rows, retained_failed_archive_bytes=requested.get("retained_failed_archive_bytes", 0),
                    buffer_bytes=requested.get("buffer_bytes", 8 * MIB), directory_inode_bound=requested.get("directory_inode_bound", 4096))
    result = {"plan": plan, "disk": disk_gate(args.filesystem, plan)}
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
