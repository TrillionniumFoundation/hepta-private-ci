"""Build an explicitly enumerated, deterministic V4 local evidence archive.

No discovery of run files, network access, scientific execution or deletion.
The independent verifier must consume the finished archive to physical EOF.
Storage checks are conservative snapshots, not filesystem reservations.
"""

import argparse
import ctypes
import ctypes.util
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import time
import zlib

sys.dont_write_bytecode = True

if __package__:
    from .archive_integrity_v4 import (MAX_MANIFEST, canonical, file_sha,
        integrity_receipt_budget, publish_no_replace, require, require_space,
        safe_name, sha, strict_json, validate_manifest)
else:
    from archive_integrity_v4 import (MAX_MANIFEST, canonical, file_sha,
        integrity_receipt_budget, publish_no_replace, require, require_space,
        safe_name, sha, strict_json, validate_manifest)


REUSED_V3_SOURCE_SHA256 = "47a2a51bc2a39bf0e07680f22b34683d25463e4d185a5af5e13758088e2f9e10"
# Reuse: V3 deterministic headers, streaming input SHA checks and no-replace
# publication. V4 adds strict input binding and worst-case storage preflight.
NESTED_ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                           ".tar.xz", ".txz", ".tar.zst", ".tar.zstd")


def header(name, size):
    item = tarfile.TarInfo(name)
    item.size, item.mode, item.mtime = size, 0o644, 0
    item.uid, item.gid, item.uname, item.gname = 0, 0, "", ""
    item.type = tarfile.REGTYPE
    item.tobuf(format=tarfile.USTAR_FORMAT)
    return item


class CheckedReader:
    def __init__(self, stream):
        self.stream, self.hasher, self.count = stream, hashlib.sha256(), 0

    def read(self, size):
        data = self.stream.read(size)
        self.hasher.update(data)
        self.count += len(data)
        return data


class ZStream(ctypes.Structure):
    """Public z_stream layout from zlib.h; zero callbacks use libz allocation."""

    _fields_ = [("next_in", ctypes.c_void_p), ("avail_in", ctypes.c_uint),
        ("total_in", ctypes.c_ulong), ("next_out", ctypes.c_void_p),
        ("avail_out", ctypes.c_uint), ("total_out", ctypes.c_ulong),
        ("msg", ctypes.c_char_p), ("state", ctypes.c_void_p),
        ("zalloc", ctypes.c_void_p), ("zfree", ctypes.c_void_p),
        ("opaque", ctypes.c_void_p), ("data_type", ctypes.c_int),
        ("adler", ctypes.c_ulong), ("reserved", ctypes.c_ulong)]


def _bound_library():
    """Require the bound provider and Python compressor to report one version."""
    candidates = [getattr(zlib, "__file__", None), None, ctypes.util.find_library("z")]
    seen, inspected = set(), []
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        label = name if name is not None else "<current process>"
        try:
            library = ctypes.CDLL(name)
            version = library.zlibVersion
            version.argtypes, version.restype = [], ctypes.c_char_p
            value = version().decode("ascii")
            inspected.append({"library": label, "version": value})
            for symbol in ("deflateInit2_", "deflateBound", "deflateEnd"):
                getattr(library, symbol)
            if value == zlib.ZLIB_RUNTIME_VERSION:
                return library, label, value
        except (OSError, AttributeError, UnicodeError):
            inspected.append({"library": label, "matching_symbols": False})
    raise ValueError("Cannot prove the gzip bound with a matching libz runtime; "
        "use a Python whose compressor matches the available libz (on this host /usr/bin/python3). "
        + json.dumps({"python_zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
                      "inspected": inspected}, sort_keys=True))


def gzip_upper_bound(source_bytes):
    """Native deflateBound for the configured gzip stream; never sample data.

    zlib's documented bound applies to Z_NO_FLUSH input and final Z_FINISH.
    gzip.GzipFile uses raw DEFLATE and an 18-byte, filename-free gzip wrapper;
    windowBits=31 configures that same wrapper for the bound calculation.
    No compressed input or scientific data is read by this function.
    """
    maximum = (1 << (8 * ctypes.sizeof(ctypes.c_ulong))) - 1
    require(type(source_bytes) is int and 0 <= source_bytes <= maximum // 2,
            "Input byte length exceeds safe libz bound range")
    library, label, version = _bound_library()
    initialize, bound, release = library.deflateInit2_, library.deflateBound, library.deflateEnd
    initialize.argtypes = [ctypes.POINTER(ZStream), ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    initialize.restype = ctypes.c_int
    bound.argtypes, bound.restype = [ctypes.POINTER(ZStream), ctypes.c_ulong], ctypes.c_ulong
    release.argtypes, release.restype = [ctypes.POINTER(ZStream)], ctypes.c_int
    stream = ZStream()
    status = initialize(ctypes.byref(stream), 6, 8, 31, 8, 0,
                        version.encode("ascii"), ctypes.sizeof(stream))
    require(status == 0, "libz could not initialize the exact gzip bound state")
    try:
        upper = int(bound(ctypes.byref(stream), source_bytes))
    finally:
        require(release(ctypes.byref(stream)) == 0, "libz bound state cleanup failed")
    require(upper >= source_bytes + 18, "libz returned an invalid or overflowing gzip bound")
    return upper, {"method": "deflateBound after deflateInit2_(6,8,31,8,0)",
        "documentation": "https://www.zlib.net/manual.html",
        "public_header_reference": "zlib.h: z_stream, deflateBound, deflateInit2_",
        "python_executable": sys.executable, "python_zlib_compile_version": zlib.ZLIB_VERSION,
        "python_zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
        "bound_library": label, "bound_libz_version": version, "runtime_versions_match": True,
        "source_bytes": source_bytes, "gzip_upper_bound_bytes": upper,
        "level": 6, "method_code": 8, "window_bits": 31, "memory_level": 8, "strategy": 0,
        "wrapper_bytes_without_optional_fields": 18,
        "flush_sequence": "Z_NO_FLUSH writes, then one Z_FINISH",
        "empirical_compression_ratio_used": False}


def storage_estimate(members, manifest_bytes, restore_members=()):
    """Worst-case archive plus complete requested literal restore on one disk."""
    require(type(manifest_bytes) is int and 0 < manifest_bytes <= MAX_MANIFEST,
            "Manifest byte length is outside the verifier limit")
    by_name = {}
    for row in members:
        name = safe_name(row["path"])
        require(name not in by_name and type(row["bytes"]) is int and row["bytes"] >= 0,
                "Invalid storage member identity")
        by_name[name] = row
    requested = [safe_name(name) for name in restore_members]
    require(len(requested) == len(set(requested)) and set(requested) <= set(by_name),
            "Restore plan contains a duplicate or absent member")
    padded = lambda length: ((length + 511) // 512) * 512
    tar_before_record_padding = 512 + padded(manifest_bytes) + 1024
    tar_before_record_padding += sum(512 + padded(row["bytes"]) for row in members)
    tar_bytes = ((tar_before_record_padding + tarfile.RECORDSIZE - 1)
                 // tarfile.RECORDSIZE) * tarfile.RECORDSIZE
    upper, method = gzip_upper_bound(tar_bytes)
    restored = sum(by_name[name]["bytes"] for name in requested)
    restore_manifest = manifest_bytes if requested else 0
    integrity_receipt = integrity_receipt_budget(manifest_bytes, members)
    build_receipt = manifest_bytes + (64 << 10)
    planned = upper + restored + restore_manifest + integrity_receipt + build_receipt
    return {"uncompressed_tar_bytes": tar_bytes,
        "tar_record_bytes": tarfile.RECORDSIZE, "tar_end_marker_bytes": 1024,
        "tar_padding_formula": "round_to_10240(sum(512+round_to_512(bytes))+1024)",
        "archive_output_upper_bound_bytes": upper, "gzip_upper_bound_method": method,
        "literal_restore_payload_bytes": restored, "literal_restore_manifest_bytes": restore_manifest,
        "restore_member_count": len(requested), "restore_members_sha256": sha(canonical(sorted(requested))),
        "integrity_receipt_allowance_bytes": integrity_receipt,
        "build_receipt_allowance_bytes": build_receipt,
        "planned_output_bytes_before_safety_reserve": planned,
        "archive_and_restore_assumed_same_filesystem": True,
        "restore_budget_is_conservative_if_destination_differs": True,
        "filesystem_metadata_and_block_rounding_covered_by_safety_reserve": True}


def build(index_path, output, receipt, *, reserve_bytes=32 << 20, use_root_reserved_blocks=False):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    originals = [Path(value) for value in (index_path, output, receipt)]
    require(not any(path.is_symlink() for path in originals), "Symlink input index or output path is forbidden")
    index_path, output, receipt = (path.resolve() for path in originals)
    partial = output.with_name(output.name + ".partial")
    require(len({index_path, output, partial, receipt}) == 4, "Input index and output paths must be distinct")
    require(not output.exists() and not partial.exists() and not partial.is_symlink()
            and not receipt.exists(), "Refusing to overwrite an archive attempt")
    require(not receipt.is_relative_to(output) and not receipt.is_relative_to(partial)
            and not output.is_relative_to(receipt), "An output file cannot be another output's directory")
    index_raw = index_path.read_bytes()
    index = strict_json(index_raw)
    require(isinstance(index, dict) and index.get("schema") == "hepta.field-bridge.v4.archive-input-index.1"
            and isinstance(index.get("entries"), list), "Unknown explicit input index")
    require(isinstance(index.get("restore_members"), list) and index["restore_members"],
            "A nonempty explicit literal restore plan is required for disk preflight")
    require(isinstance(index.get("expected_members"), list) and index["expected_members"],
            "A complete nonempty terminal input identity snapshot is required")
    rows, sources, names = [], {}, set()
    for entry in sorted(index["entries"], key=lambda row: row["path"]):
        require(isinstance(entry, dict) and set(entry) == {"source", "path"}, "Unknown input entry field")
        name, raw_source = safe_name(entry["path"]), Path(entry["source"])
        source = raw_source.resolve()
        require(name.casefold() not in names, "Duplicate or case-colliding archive name")
        require(raw_source.is_absolute() and not raw_source.is_symlink() and source.is_file(),
                "Every explicitly selected source must be an absolute regular file")
        require(not name.lower().endswith(NESTED_ARCHIVE_SUFFIXES)
                and not source.name.lower().endswith(NESTED_ARCHIVE_SUFFIXES),
                "Nested historical tar archives are outside V4 evidence scope")
        require(source not in (output, partial, receipt), "Archive outputs cannot be payload inputs")
        names.add(name.casefold())
        row = {"path": name, "bytes": source.stat().st_size, "sha256": file_sha(source)}
        header(name, row["bytes"])
        rows.append(row)
        sources[name] = source
    require(rows, "Empty evidence payload")
    require(canonical(rows) == canonical(index["expected_members"]),
            "An input changed between terminal inventory and archive build")
    manifest = {"schema": "hepta.field-bridge.v4.evidence-archive-manifest.1",
                "provenance": index["provenance"], "members": rows}
    validate_manifest(manifest)
    data = (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    header("MANIFEST.json", len(data))
    estimate = storage_estimate(rows, len(data), index["restore_members"])
    preflight = require_space(output, estimate["planned_output_bytes_before_safety_reserve"],
        reserve_bytes=reserve_bytes, use_root_reserved_blocks=use_root_reserved_blocks,
        purpose="worst-case archive, planned literal restore and both receipts")
    receipt_preflight = require_space(receipt, estimate["build_receipt_allowance_bytes"],
        reserve_bytes=reserve_bytes, use_root_reserved_blocks=use_root_reserved_blocks,
        purpose="build receipt destination, independently checked")
    # No output, directory or preserved partial attempt is created before both checks.
    output.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
                archive.addfile(header("MANIFEST.json", len(data)), io.BytesIO(data))
                for position, row in enumerate(rows, 1):
                    source = sources[row["path"]]
                    require(not source.is_symlink() and source.is_file() and source.stat().st_size == row["bytes"],
                            "An input type or size changed before archiving")
                    with source.open("rb") as stream:
                        checked = CheckedReader(stream)
                        archive.addfile(header(row["path"], row["bytes"]), checked)
                        require(checked.count == row["bytes"] and checked.hasher.hexdigest() == row["sha256"]
                                and not stream.read(1), "An input changed while archiving")
                    if position % 200 == 0:
                        print(json.dumps({"archived_files": position, "total_files": len(rows)}), flush=True)
            require(zipped.tell() == estimate["uncompressed_tar_bytes"], "Tar length differs from exact preflight")
    require(partial.stat().st_size <= estimate["archive_output_upper_bound_bytes"],
            "Archive exceeded the native gzip upper bound")
    require(file_sha(index_path) == sha(index_raw), "Explicit input index changed during packaging")
    output_hash = file_sha(partial)
    publish_no_replace(partial, output)
    result = {"schema": "hepta.field-bridge.v4.archive-build.1", "built": True,
        "independent_integrity_verification_still_required": True,
        "archive": str(output), "archive_bytes": output.stat().st_size, "archive_sha256": output_hash,
        "manifest_sha256": sha(data), "manifest_bytes": len(data), "payload_files": len(rows),
        "regular_members_including_manifest": len(rows) + 1, "payload_bytes": sum(row["bytes"] for row in rows),
        "input_index_sha256": sha(index_raw), "expected_members_required_and_matched": True,
        "builder_sha256": file_sha(__file__), "reused_v3_source_sha256": REUSED_V3_SOURCE_SHA256,
        "compression": "gzip level6, mtime0, no filename; USTAR regular files only",
        "provenance": manifest["provenance"], "storage_estimate": estimate,
        "storage_preflight": preflight, "receipt_storage_preflight": receipt_preflight,
        "network_requests": 0, "generator_or_observer_calls": 0,
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu}
    serialized = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    require(len(serialized) <= estimate["build_receipt_allowance_bytes"], "Build receipt exceeds preflight allowance")
    require_space(receipt, len(serialized), reserve_bytes=0, use_root_reserved_blocks=use_root_reserved_blocks,
                  purpose="exclusive build receipt write")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("xb") as stream:
        stream.write(serialized)
    print(json.dumps({key: result[key] for key in ("archive", "archive_bytes", "archive_sha256",
                     "manifest_sha256", "payload_files", "payload_bytes")}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--reserve-bytes", type=int, default=32 << 20)
    parser.add_argument("--use-root-reserved-blocks", action="store_true")
    args = parser.parse_args()
    build(args.index, args.output, args.receipt, reserve_bytes=args.reserve_bytes,
          use_root_reserved_blocks=args.use_root_reserved_blocks)
