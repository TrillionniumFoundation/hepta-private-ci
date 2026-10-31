"""Streaming V4 evidence integrity and exclusive, selective regular-file restore.

No tar extract()/extractall(), links, devices, directory entries, shell commands,
model loading, network access or exception allowlists are used. A restore is
published only after every archive member and both gzip layers are verified.
"""

import argparse
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import time
import zlib


SCHEMA = "hepta.field-bridge.v4.evidence-archive-manifest.1"
ROOTS = ("run", "repository", "freezes", "assets", "legacy", "operations")
CHUNK = 1 << 20
MAX_MANIFEST = 16 << 20
MAX_INNER_EXPANDED = 8 << 30
REUSED_V3_SOURCE_SHA256 = '4a6e84a996145ed1a389f9b736b876216d26595d6db9f2bb6071cc252581e8c8'
# Reuse: byte-identical SHA/CRC/EOF/atomic-publication primitives; V4 roots/schema and pre-write disk checks added.


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON object key")
        result[key] = value
    return result


def strict_json(raw):
    def invalid(value):
        raise ValueError("Nonfinite JSON constant: " + value)
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid)


def valid_digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def safe_name(value):
    require(isinstance(value, str) and 1 <= len(value.encode("utf-8")) <= 4096
            and "\\" not in value and ":" not in value and not value.startswith("/")
            and not any(ord(char) < 32 or ord(char) == 127 for char in value), "Unsafe archive member name")
    parts = value.split("/")
    require(len(parts) > 1 and parts[0] in ROOTS and all(part not in ("", ".", "..") for part in parts)
            and PurePosixPath(value).as_posix() == value, "Archive path escapes its six declared roots")
    require(not ({".git", ".ssh", ".aws", ".env", ".netrc"} & set(parts)), "Unrelated credential or repository-control path")
    return value


def validate_manifest(manifest):
    require(isinstance(manifest, dict) and manifest.get("schema") == SCHEMA
            and isinstance(manifest.get("members"), list) and 0 < len(manifest["members"]) <= 100000,
            "Invalid V4 archive manifest schema or member count")
    members = {}
    for row in manifest["members"]:
        require(isinstance(row, dict) and set(row) == {"path", "bytes", "sha256"}, "Invalid member identity record")
        path = safe_name(row["path"])
        require(path not in members and type(row["bytes"]) is int and row["bytes"] >= 0 and valid_digest(row["sha256"]),
                "Duplicate member, invalid size or invalid SHA256")
        members[path] = row
    require(list(members) == sorted(members), "Manifest members must be sorted by canonical path")
    folded = [name.casefold() for name in members]
    require(len(folded) == len(set(folded)), "Case-colliding archive members")
    for name in members:
        parts = name.split("/")
        require(not any("/".join(parts[:end]) in members for end in range(1, len(parts))),
                "A regular file is also another member's parent directory")
    provenance = manifest.get("provenance")
    require(isinstance(provenance, dict) and isinstance(provenance.get("registered_commits"), list)
            and provenance["registered_commits"] and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value)
                for value in provenance["registered_commits"]), "Missing registered commit provenance")
    protocol = provenance.get("protocol")
    require(isinstance(protocol, dict) and set(protocol) == {"path", "sha256"}, "Missing protocol provenance")
    bindings = {protocol["path"]: protocol["sha256"]}
    for key in ("source_files", "receipts", *(["archive_tools"] if "archive_tools" in provenance else [])):
        values = provenance.get(key)
        require(isinstance(values, dict) and values, "Missing source/receipt provenance bindings")
        for name, identity in values.items():
            require(name not in bindings or bindings[name] == identity, "Conflicting manifest provenance binding")
            bindings[name] = identity
    for name, identity in bindings.items():
        safe_name(name)
        require(name in members and valid_digest(identity) and members[name]["sha256"] == identity,
                "Protocol, scientific source or receipt is not bound to archived bytes")
    return members


class HashReader:
    def __init__(self, stream):
        self.stream, self.hash, self.bytes = stream, hashlib.sha256(), 0

    def read(self, size=-1):
        value = self.stream.read(size)
        self.hash.update(value)
        self.bytes += len(value)
        return value


class GzipCRC:
    """Bounded-memory CRC/ISIZE validation for every concatenated gzip member."""

    def __init__(self, name, maximum=MAX_INNER_EXPANDED):
        self.name, self.maximum = name, maximum
        self.decoder = zlib.decompressobj(31)
        self.expanded_bytes = self.members = 0

    def feed(self, data):
        while data:
            if self.decoder.eof:
                self.decoder = zlib.decompressobj(31)
            try:
                output = self.decoder.decompress(data, CHUNK)
            except zlib.error as error:
                raise ValueError(f"Inner gzip CRC/format failure: {self.name}") from error
            self.expanded_bytes += len(output)
            require(self.expanded_bytes <= self.maximum, "Inner gzip expansion exceeds declared verification limit")
            if self.decoder.eof:
                self.members += 1
                data = self.decoder.unused_data
            else:
                data = self.decoder.unconsumed_tail

    def finish(self):
        require(self.decoder.eof and self.members > 0, "Truncated or empty inner gzip: " + self.name)
        return {"path": self.name, "gzip_members": self.members, "uncompressed_bytes": self.expanded_bytes, "crc_verified": True}


def regular(info, first=False):
    require(info.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and not info.linkname and info.sparse is None
            and not any(key.startswith("GNU.sparse") for key in info.pax_headers), "Nonregular archive member is forbidden")
    require(info.size >= 0, "Negative tar member size")
    if first:
        require(info.name == "MANIFEST.json" and 0 < info.size <= MAX_MANIFEST, "MANIFEST.json must be the first bounded regular member")
    else:
        safe_name(info.name)


def publish_no_replace(staging, final):
    """Linux-only atomic publication; no portable overwrite-capable fallback.

    Constants/signature are from Linux fcntl.h and glibc stdio.h. Verification
    without selective publication remains platform independent.
    """
    require(sys.platform.startswith("linux"), "Atomic selective publication requires Linux renameat2")
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, "renameat2", None)
    require(rename is not None, "The C runtime lacks atomic no-replace renameat2")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(staging), -100, os.fsencode(final), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(final))

def available_disk(path, *, use_root_reserved_blocks=False):
    """Snapshot the target filesystem without creating directories or files."""
    candidate = Path(path).absolute()
    while not candidate.exists():
        require(candidate.parent != candidate, "No existing ancestor for storage check")
        candidate = candidate.parent
    if not candidate.is_dir():
        candidate = candidate.parent
    candidate = candidate.resolve()
    require(not use_root_reserved_blocks or (hasattr(os, "geteuid") and os.geteuid() == 0),
            "Root-reserved blocks require explicit opt-in by uid 0")
    status = os.statvfs(candidate)
    unit = status.f_frsize or status.f_bsize
    ordinary, all_free = status.f_bavail * unit, status.f_bfree * unit
    return {"existing_ancestor": str(candidate), "device": candidate.stat().st_dev,
            "fragment_bytes": unit, "unprivileged_available_bytes": ordinary,
            "all_free_bytes": all_free, "root_reserved_blocks_explicitly_enabled": use_root_reserved_blocks,
            "available_bytes_used": all_free if use_root_reserved_blocks else ordinary,
            "available_inodes": status.f_favail, "snapshot_unix_ns": time.time_ns(),
            "capacity_snapshot_only": True, "filesystem_blocks_reserved": False}


def require_space(path, payload_bytes, *, reserve_bytes=32 << 20, use_root_reserved_blocks=False,
                  purpose="archive operation"):
    require(type(payload_bytes) is int and payload_bytes >= 0 and type(reserve_bytes) is int
            and reserve_bytes >= 0, "Storage budgets must be nonnegative integers")
    observed = available_disk(path, use_root_reserved_blocks=use_root_reserved_blocks)
    needed = payload_bytes + reserve_bytes
    record = {**observed, "purpose": purpose, "payload_and_known_overhead_bytes": payload_bytes,
              "safety_reserve_bytes": reserve_bytes, "required_available_bytes": needed}
    require(observed["available_bytes_used"] >= needed,
            "Insufficient disk space; no output or staging file created: "
            + json.dumps(record, sort_keys=True, separators=(",", ":")))
    return record


def integrity_receipt_budget(manifest_bytes, members):
    """Conservative serialized receipt allowance, separate from payload copies."""
    require(type(manifest_bytes) is int and manifest_bytes > 0, "Invalid manifest byte length")
    inner_rows = sum(len(row["path"].encode("utf-8")) + 512 for row in members
                     if row["path"].lower().endswith(".gz"))
    return 3 * manifest_bytes + inner_rows + (64 << 10)



def verify_archive(archive, *, expected_sha256=None, expected_manifest_sha256=None,
                   restore_paths=(), destination=None, max_restore_bytes=100 << 20,
                   reserve_bytes=32 << 20, use_root_reserved_blocks=False):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    archive = Path(archive)
    require(archive.is_file() and not archive.is_symlink(), "Archive must be a regular local file")
    archive = archive.resolve()
    require(expected_sha256 is None or valid_digest(expected_sha256), "Invalid external archive identity")
    require(expected_manifest_sha256 is None or valid_digest(expected_manifest_sha256), "Invalid external manifest identity")
    require((destination is not None) == bool(restore_paths), "Selective restore requires both a destination and explicit members")
    requested = [safe_name(name) for name in restore_paths]
    require(len(requested) == len(set(requested)), "Duplicate restore request")
    original_stat = archive.stat()
    staging, final = None, Path(destination).resolve() if destination is not None else None
    if final is not None:
        staging = final.with_name(final.name + ".partial")
        require(not final.exists() and not staging.exists(), "Restore destination or preserved partial attempt already exists")
    observed, inner_results, seen, restored = [], [], set(), []
    storage_preflight = None
    with archive.open("rb") as physical:
        raw = HashReader(physical)
        with gzip.GzipFile(fileobj=raw, mode="rb") as compressed:
            # One-block buffering leaves every trailing tar byte available for
            # explicit zero-padding and outer gzip EOF/CRC checks below.
            with tarfile.open(fileobj=compressed, mode="r|", bufsize=512) as tar:
                first = next(iter(tar), None)
                require(first is not None, "Empty evidence archive")
                regular(first, first=True)
                with tar.extractfile(first) as stream:
                    manifest_raw = stream.read(MAX_MANIFEST + 1)
                require(len(manifest_raw) == first.size, "Manifest length differs from its tar header")
                manifest_sha = sha(manifest_raw)
                require(expected_manifest_sha256 in (None, manifest_sha), "Archive manifest differs from its external identity")
                manifest = strict_json(manifest_raw)
                expected = validate_manifest(manifest)
                require(set(requested) <= set(expected), "A requested restore member is absent from the manifest")
                require(sum(expected[name]["bytes"] for name in requested) <= max_restore_bytes, "Selective restore byte budget exceeded")
                if staging is not None:
                    restored_bytes = sum(expected[name]["bytes"] for name in requested)
                    receipt_allowance = integrity_receipt_budget(len(manifest_raw), manifest["members"])
                    storage_preflight = require_space(final,
                        restored_bytes + len(manifest_raw) + receipt_allowance, reserve_bytes=reserve_bytes,
                        use_root_reserved_blocks=use_root_reserved_blocks,
                        purpose="literal restore, manifest and verification receipt")
                    storage_preflight.update(restored_payload_bytes=restored_bytes, manifest_bytes=len(manifest_raw),
                                             verification_receipt_allowance_bytes=receipt_allowance)
                    staging.mkdir(parents=True, mode=0o700)
                    with (staging / "MANIFEST.json").open("xb") as stream:
                        stream.write(manifest_raw)
                for info in tar:
                    if info is first:
                        continue
                    regular(info)
                    name = info.name
                    require(name not in seen, "Duplicate tar member: " + name)
                    require(name in expected and info.size == expected[name]["bytes"], "Unmanifested member or header length mismatch: " + name)
                    seen.add(name)
                    content_hash, count = hashlib.sha256(), 0
                    checker = GzipCRC(name) if name.lower().endswith(".gz") else None
                    destination_stream = None
                    if name in requested:
                        target = staging / name
                        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        destination_stream = target.open("xb")
                    try:
                        with tar.extractfile(info) as payload:
                            while True:
                                block = payload.read(CHUNK)
                                if not block:
                                    break
                                content_hash.update(block)
                                count += len(block)
                                if checker is not None:
                                    checker.feed(block)
                                if destination_stream is not None:
                                    destination_stream.write(block)
                    finally:
                        if destination_stream is not None:
                            destination_stream.close()
                    record = {"path": name, "bytes": count, "sha256": content_hash.hexdigest()}
                    require(record == expected[name], "Payload SHA256 or length differs: " + name)
                    observed.append(record)
                    if checker is not None:
                        inner_results.append(checker.finish())
                    if name in requested:
                        restored.append(record)
            padding = 0
            while True:
                block = compressed.read(CHUNK)
                if not block:
                    break
                require(not any(block), "Nonzero trailing data after the tar end marker")
                padding += len(block)
                require(padding <= CHUNK, "Excessive trailing tar padding")
            require(padding >= 512, "Missing second tar end-of-archive block")
        archive_sha = raw.hash.hexdigest()
        require(raw.bytes == original_stat.st_size, "Outer gzip did not consume the entire physical archive")
    require(seen == set(expected), "Archive omitted manifest members")
    require(expected_sha256 in (None, archive_sha), "Archive differs from its external SHA256")
    after = archive.stat()
    require((after.st_ino, after.st_size, after.st_mtime_ns) == (original_stat.st_ino, original_stat.st_size, original_stat.st_mtime_ns),
            "Archive changed during verification")
    if staging is not None:
        require({row["path"] for row in restored} == set(requested), "Selective restore is incomplete")
        for row in restored:
            require(file_sha(staging / row["path"]) == row["sha256"], "Restored file readback differs")
        publish_no_replace(staging, final)
    return {"schema": "hepta.field-bridge.v4.archive-integrity.1", "passed": True, "archive": str(archive),
        "archive_bytes": original_stat.st_size, "archive_sha256": archive_sha, "manifest_sha256": manifest_sha,
        "external_archive_identity_supplied": expected_sha256 is not None,
        "provenance": manifest["provenance"], "payload_members": len(observed),
        "payload_bytes": sum(row["bytes"] for row in observed), "members": sorted(observed, key=lambda row: row["path"]),
        "outer_gzip_crc_verified_to_physical_eof": True, "all_inner_gzip_crc_verified": True,
        "inner_gzip_members": inner_results, "tar_trailing_zero_bytes": padding,
        "duplicate_unsafe_nonregular_members": 0, "exception_allowlist": [],
        "restored_root": str(final) if final else None, "restored_members": sorted(restored, key=lambda row: row["path"]),
        "restored_payload_bytes": sum(row["bytes"] for row in restored), "manifest_restored": final is not None,
        "script_sha256": file_sha(__file__), "reused_v3_source_sha256": REUSED_V3_SOURCE_SHA256,
        "storage_preflight": storage_preflight, "verification_wall_ns": time.perf_counter_ns() - started,
        "verification_cpu_ns": time.process_time_ns() - cpu, "model_native_or_network_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--restore-plan", type=Path)
    parser.add_argument("--restore-dir", type=Path)
    parser.add_argument("--max-restore-bytes", type=int, default=100 << 20)
    parser.add_argument("--reserve-bytes", type=int, default=32 << 20)
    parser.add_argument("--use-root-reserved-blocks", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Refusing to replace archive integrity evidence")
    plan = strict_json(args.restore_plan.read_bytes()) if args.restore_plan else {"members": []}
    result = verify_archive(args.archive, expected_sha256=args.expected_sha256,
        expected_manifest_sha256=args.expected_manifest_sha256, restore_paths=plan["members"],
        destination=args.restore_dir, max_restore_bytes=args.max_restore_bytes,
        reserve_bytes=args.reserve_bytes, use_root_reserved_blocks=args.use_root_reserved_blocks)
    serialized = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    require_space(args.output, len(serialized), reserve_bytes=0,
                  use_root_reserved_blocks=args.use_root_reserved_blocks, purpose="integrity receipt write")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(serialized)
    print(json.dumps({key: result[key] for key in ("passed", "archive_sha256", "payload_members", "payload_bytes", "restored_payload_bytes")}))
