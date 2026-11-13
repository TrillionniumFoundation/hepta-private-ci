#!/usr/bin/env python3
"""Review retained index bytes and immutable read records without accessing H or source."""
import base64
import hashlib
import json
import pathlib
import struct
import zlib

ROOT = pathlib.Path("/tmp/hepta-36fa-current-workspace-reconstruction-v3")
RUN = pathlib.Path("/tmp/hepta-36fa-provider-0c59-materialization-runtime-v1")
EXPECTED = pathlib.Path("/tmp/hepta-36fa-full-candidate-graph-v1/expected-inventory-v1/EXPECTED_CLEAN_INVENTORY.json")

def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}

def equal_pin(raw, pin):
    assert identity(raw) == {key: pin[key] for key in ("bytes", "sha256", "git_blob")}

review_raw = (RUN / "INDEX_FULL_READBACK.json").read_bytes()
assert identity(review_raw)["git_blob"] == "24ddb2f03a9d5fcea9cd938f67260c21ce1e478a"
review = json.loads(review_raw)
result_raw = (RUN / "RESULT.json").read_bytes()
assert identity(result_raw)["git_blob"] == "4832994442a8a1bc89ea3af7825a06310ceb7c64"
result = json.loads(result_raw)
compressed = b""
for row in review["complete_chunks"]:
    sdk_raw = (RUN / row["name"]).read_bytes()
    equal_pin(sdk_raw, row["original_sdk"])
    sdk = json.loads(sdk_raw)
    assert sdk["isError"] is False
    observed = json.loads(sdk["content"][0]["text"])
    assert observed["path"] == review["native_artifact"]
    assert observed["version"] == review["native_version"]
    assert observed["offset"] == len(compressed) == row["offset"]
    part = base64.b64decode(observed["data_base64"], validate=True)
    assert hashlib.sha256(part).hexdigest() == observed["chunk_sha256"] == row["chunk_sha256"]
    assert observed["next_offset"] == row["next_offset"] == len(compressed) + len(part)
    assert observed["eof"] is row["eof"]
    compressed += part
assert observed["eof"] is True and observed["size"] == len(compressed)
equal_pin(compressed, review["gzip"])
decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
raw = decoder.decompress(compressed) + decoder.flush()
assert decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
assert raw == (RUN / "final.new-index.raw").read_bytes()
equal_pin(raw, review["raw"])
equal_pin(raw, result["current_index"]["raw"])
assert raw[:4] == b"DIRC"
version, count = struct.unpack_from(">II", raw, 4)
assert version == 2 and count == 15237
assert hashlib.sha1(raw[:-20]).digest() == raw[-20:]
expected_raw = EXPECTED.read_bytes()
equal_pin(expected_raw, result["current_source_after"]["inventory"])
expected = json.loads(expected_raw)
expected_rows = {row["path"]: row for row in expected["files"]}
assert len(expected_rows) == count
offset = 12
paths = []
modes = {}
for _ in range(count):
    start = offset
    fields = struct.unpack_from(">10I20sH", raw, offset)
    mode, uid, gid, size, oid, flags = fields[6], fields[7], fields[8], fields[9], fields[10], fields[11]
    assert not flags & 0xF000
    end = raw.index(b"\0", offset + 62)
    path_raw = raw[offset + 62:end]
    path = path_raw.decode("utf-8", "strict")
    assert flags & 0xFFF == min(len(path_raw), 0xFFF)
    offset = start + ((end + 1 - start + 7) // 8) * 8
    assert raw[end:offset] == b"\0" * (offset - end)
    row = expected_rows[path]
    assert oid.hex() == row["index_blob"] == row["working_blob"]
    assert format(mode, "o") == row["index_mode"]
    assert size == row["bytes"] and uid == gid == 1000
    assert fields[0] > 0 and fields[2] > 0 and fields[4] == 2050 and fields[5] > 0
    paths.append(path_raw)
    modes[format(mode, "o")] = modes.get(format(mode, "o"), 0) + 1
assert paths == sorted(paths) and len(set(paths)) == count
assert {p.decode("utf-8") for p in paths} == set(expected_rows)
extensions = []
while offset < len(raw) - 20:
    name = raw[offset:offset + 4]
    size = struct.unpack_from(">I", raw, offset + 4)[0]
    body = raw[offset + 8:offset + 8 + size]
    assert len(body) == size
    extensions.append({"name": name.decode("ascii"), "bytes": size})
    if name == b"TREE":
        zero = body.index(b"\0")
        line_end = body.index(b"\n", zero + 1)
        root_count, child_count = map(int, body[zero + 1:line_end].split())
        assert body[:zero] == b"" and root_count == count
        assert body[line_end + 1:line_end + 21].hex() == result["source_tree"]
    offset += 8 + size
assert offset == len(raw) - 20
assert extensions == [{"name": "TREE", "bytes": 68848}]
report = {
    "format": "hepta-root-actual-materialized-index-review-v1",
    "result": identity(result_raw),
    "native_readback_review": identity(review_raw),
    "raw_index": identity(raw),
    "compressed_index": identity(compressed),
    "successful_chunks": len(review["complete_chunks"]),
    "continuous_fixed_version_read": True,
    "original_failed_read_retained": review["original_failed_read"]["sdk"],
    "index_version": version,
    "entries": count,
    "all_paths_modes_blobs_sizes_equal_frozen_inventory": True,
    "all_stage_assume_unchanged_extended_flags_zero": True,
    "uid_gid_1000_and_device_2050": True,
    "footer_sha1_and_cache_tree_root_verified": True,
    "extensions": extensions,
    "mode_counts": modes,
    "expected_inventory_pin": identity(expected_raw),
    "expected_inventory_is_not_a_new_H_observation": True,
    "H_calls": 0,
    "actual_filesystem_stat_equality_scope": "Producer checked fresh H filesystem stats. Root parsed actual retained index fields, but did not rescan H filesystem.",
    "qualification": False,
}
out = ROOT / "ROOT_MATERIALIZED_INDEX_REVIEW.json"
assert not out.exists()
out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
print(json.dumps({"status": "verified", "report": str(out), "pin": identity(out.read_bytes()), "entries": count, "modes": modes, "chunks": len(review["complete_chunks"])}))
