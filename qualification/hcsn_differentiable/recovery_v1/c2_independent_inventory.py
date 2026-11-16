"""Read-only, fail-closed structural inventory for a six-attempt HCSN C2 run.

Producer result JSON, checkpoint files and journals are never independent replay.
Only reports bytes/status/identities; NEVER confers scientific or production GO.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

NAMES = tuple(f"hcsn-s{s}-lr{lr}" for s in (101, 211, 307) for lr in ("0.001", "0.003"))
MAX_RESULT = 16 * 1024 * 1024
MAX_JOURNAL = 32 * 1024 * 1024


class InvalidEvidence(ValueError):
    pass


def _no_duplicate_keys(items):
    result = {}
    for key, value in items:
        if key in result:
            raise InvalidEvidence("duplicate JSON key: " + key)
        result[key] = value
    return result


def _nonfinite(value):
    raise InvalidEvidence("nonfinite JSON constant: " + value)


def _regular_bytes(path: Path, limit: int):
    """No symlink or special-file traversal; detect mid-read metadata changes."""
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise InvalidEvidence("not a bounded regular file")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if (len(raw) != before.st_size or len(raw) > limit
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
        raise InvalidEvidence("file changed during read or exceeded bound")
    return raw, {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _json(raw):
    return json.loads(raw, object_pairs_hook=_no_duplicate_keys, parse_constant=_nonfinite)


def _safe_read(path, cap=MAX_RESULT):
    try:
        return _regular_bytes(path, cap)
    except FileNotFoundError:
        return None


def audit(fits: Path, controller: Path, inventory: Path, *, journal_sha256: str | None = None):
    """A second-process structural audit, not a GPU/model replay or original terminal."""
    fits, controller = Path(fits), Path(controller)
    frozen_raw, frozen_id = _regular_bytes(Path(inventory), 1 << 20)
    expected = _json(frozen_raw)
    if not isinstance(expected, dict) or expected.get("schema") != "hcsn-original-c2-fits-readonly-inventory-v1":
        raise InvalidEvidence("unsupported frozen inventory")
    original_root = expected.get("original_fits_root")
    if original_root is not None and (type(original_root) is not str or str(fits) != original_root):
        raise InvalidEvidence("input fits root differs from frozen inventory")
    records = expected.get("files")
    if not isinstance(records, list) or len(records) != 8:
        raise InvalidEvidence("frozen inventory is not the original eight-file roster")
    by_file = {}
    for item in records:
        if not isinstance(item, dict) or item.get("candidate") not in NAMES or item.get("file") not in ("result.json", "interrupted.pt", "best.pt"):
            raise InvalidEvidence("unexpected file in frozen manifest")
        key = (item["candidate"], item["file"])
        if key in by_file or type(item.get("size_bytes")) is not int or item["size_bytes"] < 0:
            raise InvalidEvidence("duplicate or invalid manifest entry")
        if not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64:
            raise InvalidEvidence("missing file digest")
        by_file[key] = item
    checks, complete, misses = [], 0, []
    for name in NAMES:
        p = fits / name
        item = _safe_read(p / "result.json")
        row = {"name": name, "producer_result_present": item is not None,
               "producer_claim": None, "structural_status": "MISSING",
               "checkpoint_semantically_replayed": False}
        if item is not None:
            raw, file_id = item
            row["result_identity"] = file_id
            ref = by_file.get((name, "result.json"))
            if ref is None:
                row["structural_status"] = "UNPINNED_RESULT"
            elif file_id != {"bytes": ref["size_bytes"], "sha256": ref["sha256"]}:
                row["structural_status"] = "CHANGED_RESULT"
            else:
                try:
                    value = _json(raw)
                    seed, lr = name.split("-")[1:3]
                    good = (isinstance(value, dict)
                            and value.get("schema") == "hcsn-c2-soft-wall-continuation-v1"
                            and value.get("arm") == "hcsn"
                            and type(value.get("seed")) is int
                            and value["seed"] == int(seed[1:])
                            and type(value.get("learning_rate")) in (int, float)
                            and value["learning_rate"] == float(lr[2:])
                            and value.get("production_execution") is True
                            and value.get("confirmation_access") is False
                            and value.get("source_and_parent_inputs_unchanged") is True
                            and value.get("common_and_physical_weights_unchanged") is True
                            and isinstance(value.get("source_before"), dict)
                            and value.get("source_before") == value.get("source_after"))
                    row["producer_claim"] = value.get("status") if isinstance(value, dict) else None
                    if good and value.get("status") == "completed_development" and value.get("training_adequacy_established") is True:
                        row["structural_status"] = "PINNED_PRODUCER_COMPLETED"
                        row["epochs"] = value.get("cumulative_epochs_completed")
                        complete += 1
                    else:
                        row["structural_status"] = "SCHEMA_OR_TERMINAL_HOLD"
                except (ValueError, TypeError, KeyError) as exc:
                    row["structural_status"] = "INVALID_RESULT_JSON"
                    row["parse_error"] = type(exc).__name__
        else:
            misses.append(name)
        for filename in ("interrupted.pt", "best.pt"):
            ref = by_file.get((name, filename))
            if ref:
                current = _safe_read(p / filename, MAX_RESULT)
                if current is None:
                    row[filename] = "MISSING"
                else:
                    _, found = current
                    row[filename] = ("ZERO_INVALID" if found["bytes"] == 0
                        else "BYTE_IDENTICAL_UNREPLAYED" if found == {"bytes": ref["size_bytes"], "sha256": ref["sha256"]}
                        else "MUTATED")
        checks.append(row)
    try:
        journal = _safe_read(controller / "commands.jsonl", MAX_JOURNAL)
        if journal is None:
            journal_report = {"present": False, "complete_rows": 0, "torn": True}
        else:
            raw, file_id = journal
            valid, torn = 0, False
            for line in raw.splitlines(keepends=True):
                if not line.endswith(b"\n"):
                    torn = True
                    break
                try:
                    row = _json(line)
                    if not isinstance(row, dict):
                        raise InvalidEvidence("journal row not an object")
                except (ValueError, TypeError):
                    torn = True
                    break
                valid += 1
            journal_report = {"present": True, **file_id,
                "complete_rows": valid, "torn": torn,
                "expected_sha256_match": file_id["sha256"] == journal_sha256 if journal_sha256 else None}
    except (InvalidEvidence, OSError) as exc:
        journal_report = {"present": True, "read_error": type(exc).__name__, "complete_rows": 0, "torn": True}
    original_result = _safe_read(controller / "RESULT.json")
    return {"schema": "hcsn-c2-independent-structural-inventory-v1",
            "original_job_id": expected.get("original_job_id"),
            "manifest_identity": frozen_id, "expected_producer_attempts": 6,
            "pinned_producer_completed": complete, "producer_missing": misses,
            "checks": checks, "controller_result_present": original_result is not None,
            "controller_journal": journal_report,
            "all_six_independently_replayed": False,
            "full_resource_bill_verified": False,
            "scientific_admission": "HOLD_NO_GO",
            "scope": "independent READ-ONLY structural bytes and declared producer metadata; no model load or actual native wait4 terminal verification"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fits", type=Path, required=True)
    parser.add_argument("--controller", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--journal-sha256", default=None)
    ns = parser.parse_args(argv)
    result = audit(ns.fits, ns.controller, ns.inventory, journal_sha256=ns.journal_sha256)
    json.dump(result, sys.stdout, sort_keys=True, indent=2, allow_nan=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

