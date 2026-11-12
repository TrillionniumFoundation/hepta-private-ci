#!/usr/bin/env python3
"""Offline, one-candidate reconstruction; never runs Git or edits a repository."""
import argparse
import collections
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import struct
import traceback

RAW_BYTES = 2072488
AFTER_SHA256 = "b19fab7a860a4281331096bd6a9c2ab5b6b9ef95ff8411e9f757cd1373380f15"
AFTER_GIT_BLOB = "80bad59e9314c6e9a9161f23574303ee9ab1b2ad"
BEFORE_SHA256 = "111345e57b5b7276c8fdb4e91302c7bafb6d7c8ca905f83dd1a6c72a28154a16"
GZIP_BYTES = 720274
GZIP_SHA256 = "2affa928d31701597402ee6392e6ab6eb9cbdcb8ea65b8bc5119f7570b828002"
GZIP_GIT_BLOB = "e44d92d6551380dfbd886170b703fdb09601afbb"
INVENTORY_SHA256 = "bca1a7399820966d3167a26f89355898a9ea9a7169938ffa27e7dd9576fc1711"
STAT_FIELDS = ((0, "ctime_seconds"), (4, "ctime_nanoseconds"),
               (8, "mtime_seconds"), (12, "mtime_nanoseconds"),
               (16, "device"), (20, "inode"), (28, "uid"),
               (32, "gid"), (36, "file_size"))


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob_sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def analyze(gz_path, inventory_path, output):
    compressed = gz_path.read_bytes()
    require(identity(compressed) == {"bytes": GZIP_BYTES, "sha256": GZIP_SHA256,
                                   "git_blob_sha": GZIP_GIT_BLOB}, "actual gzip identity mismatch")
    data = gzip.decompress(compressed)
    require(identity(data) == {"bytes": RAW_BYTES, "sha256": AFTER_SHA256,
                             "git_blob_sha": AFTER_GIT_BLOB}, "actual after index identity mismatch")
    require(hashlib.sha1(data[:-20]).digest() == data[-20:], "actual index checksum mismatch")
    inv_raw = inventory_path.read_bytes()
    require(hashlib.sha256(inv_raw).hexdigest() == INVENTORY_SHA256, "inventory identity mismatch")
    inv = json.loads(inv_raw)
    require(inv["source"] == {"head": "86dd56a930277e0d1aef3e475e35c2b5d60b43b7",
                             "tree": "383ab85c39ef9d848252ef5c25922d13d9fae6c6", "status": ""},
            "inventory source mismatch")
    inventory = {row["path"].encode(): row for row in inv["files"]}
    require(len(inventory) == len(inv["files"]) == inv["tracked_entries"] == 15188,
            "inventory cardinality mismatch")
    signature, version, count = struct.unpack_from(">4sII", data)
    require(signature == b"DIRC", "unknown index magic")
    require(version in (2, 3), "index version unsupported by this narrow parser")
    require(count == 15188, "index count mismatch")
    result = bytearray(data)
    permitted = bytearray(len(data))
    position = 12
    previous_key = None
    records = []
    field_counts = collections.Counter()
    seen = set()
    flags_counts = collections.Counter()
    for number in range(count):
        start = position
        require(start + 62 <= len(data) - 20, "truncated index entry")
        fields = struct.unpack_from(">10I", data, start)
        oid = data[start + 40:start + 60].hex()
        flags = struct.unpack_from(">H", data, start + 60)[0]
        extended = None
        name_at = start + 62
        if flags & 0x4000:
            require(version == 3, "extended flag in version 2")
            extended = struct.unpack_from(">H", data, name_at)[0]
            require(extended & 0x9FFF == 0, "unknown extended flag")
            name_at += 2
        end_name = data.index(b"\0", name_at, len(data) - 20)
        path = data[name_at:end_name]
        require(path and not path.startswith(b"/") and not path.endswith(b"/"), "invalid path")
        require(not any(x in (b".", b"..", b".git") for x in path.split(b"/")), "invalid path component")
        require(flags & 0xFFF == min(len(path), 0xFFF), "flags pathname length mismatch")
        stage = (flags >> 12) & 3
        require(stage == 0, "nonzero index stage")
        key = (path, stage)
        require(previous_key is None or previous_key < key, "index order or duplicate mismatch")
        previous_key = key
        require(path in inventory, "index path not in complete inventory")
        row = inventory[path]
        require(fields[6] == int(row["index_mode"], 8) and oid == row["index_blob"],
                "index mode/OID differs from complete physical inventory")
        require(row["stable"] and row["matches_index"] and row["working_blob"] == oid,
                "inventory does not prove physical contents match index")
        seen.add(path)
        position = start + ((end_name + 1 - start + 7) // 8) * 8
        require(position <= len(data) - 20 and not any(data[end_name:position]), "invalid index padding")
        changed = {}
        for offset, name in STAT_FIELDS:
            value = struct.unpack_from(">I", data, start + offset)[0]
            if value:
                changed[name] = value
                field_counts[name] += 1
            result[start + offset:start + offset + 4] = b"\0" * 4
            permitted[start + offset:start + offset + 4] = b"\1" * 4
        flags_counts[(flags >> 12, extended)] += 1
        records.append({"number": number, "path": path.decode(), "entry_offset": start,
                        "entry_bytes": position - start, "mode": row["index_mode"],
                        "oid": oid, "flags": flags, "extended_flags": extended,
                        "stage": stage, "nonzero_stat_before_zeroing": changed})
    require(seen == set(inventory), "complete index/inventory path sets differ")
    extensions_at = position
    extensions = []
    while position < len(data) - 20:
        require(position + 8 <= len(data) - 20, "truncated extension header")
        sig, size = struct.unpack_from(">4sI", data, position)
        end = position + 8 + size
        require(end <= len(data) - 20, "extension exceeds index")
        extensions.append({"signature_hex": sig.hex(), "signature_ascii": sig.decode("ascii"),
                           "offset": position, "payload_bytes": size,
                           "complete_header_and_payload_identity": identity(data[position:end])})
        position = end
    require(position == len(data) - 20, "invalid extension termination")
    require(result[extensions_at:-20] == data[extensions_at:-20], "extension bytes changed")
    result[-20:] = hashlib.sha1(result[:-20]).digest()
    permitted[-20:] = b"\1" * 20
    require(all(a == b or allowed for a, b, allowed in zip(data, result, permitted)),
            "candidate changed bytes outside nine stat fields and checksum")
    candidate = bytes(result)
    matched = len(candidate) == RAW_BYTES and hashlib.sha256(candidate).hexdigest() == BEFORE_SHA256
    name = "index.before.exactly_recovered.bin" if matched else "index.zero_stat_candidate.UNMATCHED.bin"
    (output / name).write_bytes(candidate)
    record_bytes = (json.dumps(records, ensure_ascii=False, indent=2) + "\n").encode()
    (output / "entry-stat-audit.json").write_bytes(record_bytes)
    return {"schema": "hepta.utility.index-stat-recovery.v1", "qualification": False,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "EXACT_BEFORE_BYTES_RECONSTRUCTED" if matched else "UNKNOWN_BEFORE_BYTES_NOT_MATCHED",
            "method": "One candidate: zero only nine documented stat uint32 fields per entry; preserve every other byte except recomputed trailing SHA1.",
            "native_before_read_performed": False, "native_git_version": "Unknown",
            "actual_writer_identity": "Unknown; timestamp and official Git diff behavior support an inference only",
            "original_maintenance_result_status": "UNKNOWN", "original_fix_returncode": 101,
            "original_fmt_status": "not_run", "original_records_reclassified": False,
            "source_edited": False, "native_commands_run": False, "gate_run": False,
            "input_gzip_path": str(gz_path), "input_gzip": identity(compressed),
            "input_after_index": identity(data), "complete_inventory": identity(inv_raw),
            "index_header": {"version": version, "entries": count},
            "actual_footer_sha1": data[-20:].hex(), "reconstructed_footer_sha1": candidate[-20:].hex(),
            "reconstructed_candidate": {"path": name, **identity(candidate)},
            "expected_before_sha256": BEFORE_SHA256, "matches_independent_original_before_identity": matched,
            "changed_entries": sum(bool(row["nonzero_stat_before_zeroing"]) for row in records),
            "nonzero_stat_fields_by_name": dict(field_counts),
            "flags_counts": [{"upper_flags_nibble": key[0], "extended_flags": key[1], "entries": value}
                             for key, value in flags_counts.items()],
            "extensions": extensions, "all_extension_bytes_preserved": True,
            "all_modes_oids_paths_stages_flags_and_padding_preserved": True,
            "full_inventory_mode_oid_path_check": True,
            "entry_audit": {"path": "entry-stat-audit.json", **identity(record_bytes)},
            "documentation": ["https://github.com/git/git/blob/v2.43.0/Documentation/gitformat-index.txt",
                              "https://github.com/git/git/blob/v2.43.0/Documentation/config/diff.txt",
                              "https://github.com/git/git/blob/v2.43.0/builtin/diff.c"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index-gzip", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=False, exist_ok=False)
    try:
        report = analyze(args.index_gzip, args.inventory, args.output)
    except Exception:
        report = {"schema": "hepta.utility.index-stat-recovery.v1", "qualification": False,
                  "status": "UNKNOWN_ANALYSIS_ERROR", "traceback": traceback.format_exc(),
                  "original_records_reclassified": False, "source_edited": False,
                  "native_commands_run": False, "gate_run": False}
    (args.output / "REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "EXACT_BEFORE_BYTES_RECONSTRUCTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
