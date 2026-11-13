#!/usr/bin/env python3
"""Archive the handed-off 72 frozen control files only; no H or control execution."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat

SOURCE = Path("/tmp/hepta-36fa-new-source-materializer-hold-v1")
OUTPUT = Path(__file__).resolve().parent
LIMIT = 512000
PART = 262144
HANDOFF_PIN = {
    "bytes": 7201,
    "sha256": "989f07ffb70bd559089fe1e3e1098dc975fcf9e23408b76e482163321f61cc23",
    "git_blob": "7cc64145508a1961be32532a0595b2fada1ca65a",
}


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def stamp(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid, s.st_nlink,
            s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def exact_read(path):
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        first = os.fstat(stream.fileno())
        raw = stream.read()
        last = os.fstat(stream.fileno())
    assert stamp(before) == stamp(first) == stamp(last) == stamp(path.lstat())
    assert len(raw) == before.st_size
    return raw


def write(relative, raw):
    assert len(raw) <= LIMIT and not Path(relative).is_absolute()
    assert all(part not in ("", ".", "..") for part in Path(relative).parts)
    path = OUTPUT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    assert exact_read(path) == raw
    return {"path": relative, "local_path": str(path), **identity(raw)}


def main():
    handed_off = exact_read(SOURCE / "GIT_READBACK_LEDGER.v2.json")
    assert identity(handed_off) == HANDOFF_PIN
    ledger = json.loads(handed_off)
    assert ledger["directory"] == str(SOURCE) and len(ledger["rows"]) == 24
    selected = []
    control_readback = []
    for row in ledger["rows"]:
        name = row["name"]
        assert Path(name).name == name
        raw = exact_read(SOURCE / name)
        assert identity(raw) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
        assert row["actual_create"] is True and row["full_get_equal"] is True
        create_name = name + ".GITHUB_CREATE.original.json"
        get_name = name + ".GITHUB_GET.original.json"
        create_raw = exact_read(SOURCE / create_name)
        get_raw = exact_read(SOURCE / get_name)
        create = json.loads(create_raw)
        fetched = json.loads(get_raw)
        assert create["structuredContent"]["sha"] == row["git_blob"]
        assert fetched["structuredContent"]["content"].encode() == raw
        control_readback.append({"name": name, **identity(raw),
                                 "saved_original_create_matches": True,
                                 "saved_full_GET_complete_content_equal": True})
        selected += [(name, "frozen_control", raw),
                     (create_name, "original_create_SDK", create_raw),
                     (get_name, "original_full_GET_SDK", get_raw)]
    assert len(selected) == 72 and len({name for name, _, _ in selected}) == 72
    leaves = []
    entries = []
    for name, role, raw in selected:
        entry = {"logical_name": name, "role": role, "source_path": str(SOURCE / name),
                 "original": identity(raw)}
        if len(raw) <= LIMIT:
            leaf = write("original/" + name, raw)
            leaves.append(leaf)
            entry["storage"] = {"kind": "direct_UTF8_bytes", "leaf": leaf}
        else:
            compressed = gzip.compress(raw, mtime=0)
            assert gzip.decompress(compressed) == raw
            parts = []
            for number, offset in enumerate(range(0, len(compressed), PART), 1):
                chunk = compressed[offset:offset + PART]
                leaf = write("encoded/" + name + ".part-%03d.b64" % number,
                             base64.b64encode(chunk) + b"\n")
                leaves.append(leaf)
                parts.append({**leaf, "decoded_offset": offset,
                              "decoded_bytes": len(chunk), "decoded_sha256": hashlib.sha256(chunk).hexdigest()})
            entry["storage"] = {"kind": "lossless_gzip_base64_parts",
                                "gzip": identity(compressed), "gzip_mtime": 0,
                                "decoded_part_ceiling": PART, "parts": parts,
                                "raw_blob_direct_GET_availability_not_asserted_by_this_encoding": True}
        entries.append(entry)
    assert len(leaves) == len({leaf["path"] for leaf in leaves})
    for entry in entries:
        storage = entry["storage"]
        if storage["kind"] == "direct_UTF8_bytes":
            raw = exact_read(OUTPUT / storage["leaf"]["path"])
            assert identity(raw) == {key: storage["leaf"][key] for key in ("bytes", "sha256", "git_blob")}
        else:
            compressed = bytearray()
            for part in storage["parts"]:
                wire = exact_read(OUTPUT / part["path"])
                assert identity(wire) == {key: part[key] for key in ("bytes", "sha256", "git_blob")}
                assert wire.endswith(b"\n") and b"\n" not in wire[:-1]
                decoded = base64.b64decode(wire[:-1], validate=True)
                assert len(compressed) == part["decoded_offset"]
                assert len(decoded) == part["decoded_bytes"] and hashlib.sha256(decoded).hexdigest() == part["decoded_sha256"]
                compressed.extend(decoded)
            assert identity(compressed) == storage["gzip"]
            raw = gzip.decompress(compressed)
        assert identity(raw) == entry["original"]
        assert raw == exact_read(Path(entry["source_path"]))
    assert exact_read(SOURCE / "GIT_READBACK_LEDGER.v2.json") == handed_off
    handoff = write("HANDOFF_LEDGER.original.json", handed_off)
    manifest = {
        "format": "hepta-new-source-fixed-controls-lossless-manifest-v1",
        "scope": "Only the handed-off24 frozen controls plus their48 existing original create/full-GET SDKs; excludes staging runtime and materialization runtime.",
        "handoff_ledger": handoff,
        "input_count": 72, "control_count": 24, "original_SDK_count": 48,
        "original_total_bytes": sum(len(raw) for _, _, raw in selected),
        "maximum_evidence_leaf_bytes": LIMIT,
        "direct_input_count": sum(entry["storage"]["kind"] == "direct_UTF8_bytes" for entry in entries),
        "encoded_input_count": sum(entry["storage"]["kind"] == "lossless_gzip_base64_parts" for entry in entries),
        "input_representation_leaf_count": len(leaves),
        "entries": entries,
        "native_observation_or_execution_performed": False,
        "current_materialization_result_included": False,
        "qualification": False,
    }
    manifest_leaf = write("ENCODING_MANIFEST.json", encoded(manifest))
    review = {
        "format": "hepta-new-source-fixed-controls-lossless-review-v1",
        "status": "EXACT72_LOCAL_INPUTS_AND_ALL_LOSSLESS_REPRESENTATIONS_VERIFIED",
        "manifest": manifest_leaf,
        "control_full_readback_checks": control_readback,
        "all72_complete_original_bytes_reconstructed_equal": True,
        "all72_source_files_unchanged_at_final_reread": True,
        "input_representation_leaf_count": len(leaves),
        "maximum_actual_input_representation_leaf_bytes": max(leaf["bytes"] for leaf in leaves),
        "unbounded_raw_evidence_leaf_exceptions": 0,
        "transport_encoding_is_new_local_representation_of_original_bytes": True,
        "H_calls": 0, "source_or_ref_writes": False, "qualification": False,
        "actual_Git_uploads_of_representations": "Pending separate create/full-GET ledger; not inferred from local serialization."
    }
    review_leaf = write("ARCHIVE_REVIEW.json", encoded(review))
    queue = {"format": "hepta-fixed-controls-archive-upload-queue-v1",
             "entries": leaves + [handoff, manifest_leaf, review_leaf],
             "original_inputs": 72, "source_closed_set_unchanged": True}
    write("UPLOAD_QUEUE.json", encoded(queue))
    print(json.dumps({key: value for key, value in manifest.items() if key not in ("entries", "handoff_ledger")}, sort_keys=True))


if __name__ == "__main__":
    main()
