#!/usr/bin/env python3
"""Verify the recovered C2 selected-state archive using only the standard library.

No archive member is extracted or executed, and no checkpoint is deserialized.
The identity constants bind this verifier to the observed original archive.
The result output is created exclusively; an existing result is never replaced.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import platform
import stat
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath


EXPECTED_ARCHIVE_SHA256 = "a1f624d88b3e240b3e583987210a1422c47cbab92ecd59beee5a1c6b28b2d92b"
EXPECTED_ARCHIVE_BYTES = 4_368_037
EXPECTED_SOURCE_FILES = 368
EXPECTED_SOURCE_BYTES = 16_003_349
EXPECTED_SOURCE_HEAD = "4ed61beacd9e8cf08cd1f7f8c938b75d747149e4"
EXPECTED_MANIFEST_SHA256 = "f82667a9edf34646cb760c315bfaa10b1102e76abbad7a015c8d0c0cd2d75ae5"


class VerificationFailure(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise VerificationFailure(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def reject_nonfinite(value):
    raise VerificationFailure(f"nonfinite JSON constant: {value}")


def strict_json(data: bytes):
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique_object,
                      parse_constant=reject_nonfinite)


def safe_path(name: str) -> bool:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    return (not path.is_absolute() and all(x not in ("", ".", "..") for x in name.split("/"))
            and str(path) == name)


def valid_sha(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def regular_bytes(path: Path) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise VerificationFailure(f"input is not a regular file: {path.name}")
    data = path.read_bytes()
    after = path.lstat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise VerificationFailure(f"input changed during read: {path.name}")
    if len(data) != before.st_size:
        raise VerificationFailure(f"input byte count changed: {path.name}")
    return data


def snapshot(directory: Path):
    result = {}
    for path in sorted(directory.iterdir()):
        data = regular_bytes(path)
        result[path.name] = {"bytes": len(data), "sha256": sha256(data)}
    return result


def verify(directory: Path, result: dict):
    def require(condition, message):
        if not condition:
            raise VerificationFailure(message)
        result["checks_passed"] += 1

    before = snapshot(directory)
    result["input_files"] = before
    parts_data = regular_bytes(directory / "ARCHIVE-PARTS.json")
    source_data = regular_bytes(directory / "ORIGINAL-SOURCE-MANIFEST.json")
    parts = strict_json(parts_data)
    source = strict_json(source_data)
    require(isinstance(parts, dict) and isinstance(source, dict), "manifest root must be an object")
    require(parts["schema"] == "hcsn-original-c2-selected-archive-parts-v1", "unexpected parts schema")
    require(source["schema"] == "hcsn-c2-original-selected-state-archive-v1", "unexpected source schema")
    require(parts["source_head"] == EXPECTED_SOURCE_HEAD, "source head differs from pinned identity")
    require(sha256(source_data) == EXPECTED_MANIFEST_SHA256, "source manifest differs from pinned identity")
    require(parts["qualification"] == source["qualification"] == "HOLD_NO_GO", "qualification differs")
    require(parts["original_controller_terminal"] == source["original_terminal"] == "unknown",
            "original terminal is no longer unknown")
    require(type(parts["archive_bytes"]) is int and parts["archive_bytes"] == EXPECTED_ARCHIVE_BYTES,
            "unexpected declared archive byte count")
    require(parts["archive_sha256"] == EXPECTED_ARCHIVE_SHA256, "archive hash differs from pinned identity")
    require(type(parts["original_source_file_count"]) is int
            and parts["original_source_file_count"] == EXPECTED_SOURCE_FILES, "unexpected declared source file count")
    require(type(parts["original_source_uncompressed_bytes"]) is int
            and parts["original_source_uncompressed_bytes"] == EXPECTED_SOURCE_BYTES,
            "unexpected declared source byte count")
    require(type(parts["part_size_limit_bytes"]) is int and 0 < parts["part_size_limit_bytes"] <= 450_000,
            "invalid part size limit")
    require(isinstance(parts["parts"], list) and len(parts["parts"]) == 10, "expected ten archive parts")

    names = []
    offset = 0
    archive = io.BytesIO()
    for number, part in enumerate(parts["parts"]):
        require(isinstance(part, dict), f"part {number}: metadata must be an object")
        name = part["path"]
        require(safe_path(name) and "/" not in name and name not in names,
                f"part {number}: unsafe or duplicate filename")
        require(name == f"original-c2-selected-state.zip.part-{number:02d}",
                f"part {number}: filename/order mismatch")
        require(type(part["offset"]) is int and part["offset"] == offset,
                f"part {number}: offset is not contiguous in listed order")
        require(type(part["bytes"]) is int and 0 < part["bytes"] <= parts["part_size_limit_bytes"],
                f"part {number}: invalid declared size")
        require(valid_sha(part["sha256"]), f"part {number}: invalid hash")
        data = regular_bytes(directory / name)
        require(len(data) == part["bytes"], f"part {number}: actual byte count differs")
        require(sha256(data) == part["sha256"], f"part {number}: SHA-256 differs")
        archive.write(data)
        offset += len(data)
        names.append(name)
    require(set(before) == {*names, "ARCHIVE-PARTS.json", "ORIGINAL-SOURCE-MANIFEST.json", "README.md"},
            "archive input directory has missing or unexpected files")
    require(offset == EXPECTED_ARCHIVE_BYTES, "assembled archive byte count differs")
    assembled_sha = sha256(archive.getvalue())
    require(assembled_sha == EXPECTED_ARCHIVE_SHA256, "assembled archive SHA-256 differs")
    result["archive"] = {"parts_checked": len(names), "part_order_offsets_sizes_and_hashes_match": True,
                         "bytes": offset, "sha256": assembled_sha}

    files = source["files"]
    require(isinstance(files, dict) and len(files) == EXPECTED_SOURCE_FILES, "source manifest file count differs")
    for name, identity in files.items():
        require(safe_path(name) and name != "MANIFEST.json", f"unsafe source member: {name!r}")
        require(isinstance(identity, dict) and type(identity["bytes"]) is int and identity["bytes"] >= 0
                and valid_sha(identity["sha256"]), f"invalid source member identity: {name!r}")
    require(sum(item["bytes"] for item in files.values()) == EXPECTED_SOURCE_BYTES,
            "declared aggregate source bytes differ")

    aggregate_bytes = 0
    observed = {}
    archive.seek(0)
    with zipfile.ZipFile(archive, "r") as zipped:
        infos = zipped.infolist()
        zip_names = [info.filename for info in infos]
        require(len(zip_names) == len(set(zip_names)), "duplicate ZIP member name")
        require(set(zip_names) == set(files) | {"MANIFEST.json"}, "ZIP member set differs from source manifest")
        for info in infos:
            require(safe_path(info.filename) and not info.is_dir(), f"unsafe or non-file ZIP member: {info.filename!r}")
            file_type = stat.S_IFMT(info.external_attr >> 16)
            require(file_type in (0, stat.S_IFREG), f"nonregular ZIP member: {info.filename!r}")
            require(not (info.flag_bits & 1), f"encrypted ZIP member: {info.filename!r}")
        require(zipped.testzip() is None, "ZIP CRC verification failed")
        embedded = zipped.read("MANIFEST.json")
        require(embedded == source_data, "embedded manifest is not byte-identical to external source manifest")
        # Read each source member fully, checking the ZIP CRC again as the stream reaches EOF.
        # No Python, NumPy, Torch, pickle, or other member format is imported or decoded.
        for name, identity in files.items():
            digest = hashlib.sha256()
            count = 0
            with zipped.open(name, "r") as member:
                while True:
                    block = member.read(1024 * 1024)
                    if not block:
                        break
                    count += len(block)
                    digest.update(block)
            actual = {"bytes": count, "sha256": digest.hexdigest()}
            require(actual["bytes"] == identity["bytes"], f"member byte count differs: {name}")
            require(actual["sha256"] == identity["sha256"], f"member SHA-256 differs: {name}")
            observed[name] = actual
            aggregate_bytes += count
        require(aggregate_bytes == EXPECTED_SOURCE_BYTES, "actual aggregate source bytes differ")
        result["zip"] = {"all_member_crc_checks_passed": True, "total_members": len(infos),
                         "source_members_checked": len(observed), "source_bytes_checked": aggregate_bytes,
                         "embedded_manifest_bytes": len(embedded), "embedded_manifest_sha256": sha256(embedded),
                         "embedded_manifest_matches_external_bytes": True,
                         "total_uncompressed_bytes": sum(info.file_size for info in infos),
                         "missing_source_members": [], "unexpected_members": [],
                         "explanatory_metadata_member": "MANIFEST.json"}

    result["selected_content_counts"] = {
        "immutable_epoch_commit_records": sum("/commits/epoch-" in name and name.endswith(".json") for name in files),
        "nonempty_best_checkpoints": sum(name.endswith("/best.pt") and row["bytes"] > 0 for name, row in observed.items()),
        "nonempty_last_checkpoints": sum(name.endswith("/last.pt") and row["bytes"] > 0 for name, row in observed.items()),
        "zero_byte_source_members": sum(row["bytes"] == 0 for row in observed.values()),
        "nonempty_checkpoint_payloads": sum(name.endswith(".pt") and row["bytes"] > 0 for name, row in observed.items()),
    }
    result["verified_source_inventory_sha256"] = sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    require(snapshot(directory) == before, "input files changed during verification")
    result["input_bytes_unchanged"] = True
    result["qualification"] = "HOLD_NO_GO"
    result["original_controller_terminal"] = "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-directory", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve()
    script_hash = sha256(regular_bytes(source))
    directory = args.archive_directory.resolve()
    result_path = args.result.resolve()
    if result_path == directory or directory in result_path.parents:
        parser.error("result must be outside the original input directory")
    result = {
        "schema": "hcsn-original-c2-selected-archive-independent-verification-v1",
        "status": "FAIL", "checks_passed": 0,
        "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "script_sha256": script_hash, "archive_directory": str(directory),
        "runtime": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                    "executable": sys.executable, "platform": platform.platform()},
        "scope": "Independent byte-integrity verification only; no extraction, checkpoint deserialization, training, or adoption.",
        "checkpoint_deserialization_performed": False,
        "original_controller_terminal_inferred": False,
        "errors": [],
    }
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    try:
        verify(directory, result)
        if sha256(regular_bytes(source)) != script_hash:
            raise VerificationFailure("verifier source changed during execution")
        result["verifier_source_unchanged"] = True
        result["status"] = "PASS"
    except Exception as exc:
        result["errors"].append({"type": type(exc).__name__, "message": str(exc)})
    result["wall_seconds"] = time.perf_counter() - start_wall
    result["cpu_seconds"] = time.process_time() - start_cpu
    result["completed_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with result_path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": result["status"], "checks_passed": result["checks_passed"],
                      "result": str(result_path), "errors": result["errors"]}, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
