#!/usr/bin/env python3
"""Copy fixed, already closed inputs; reconstruct scope chunks without native work."""
import ast
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def put(path, raw):
    target = HERE / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": path, **pin(raw)}


def encode(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode()


def main():
    mapping = []
    def copy(source, destination, expected=None):
        raw = (BASE / source).read_bytes()
        if expected is not None:
            assert all(pin(raw)[key] == expected[key] for key in expected), source
        row = put(destination, raw)
        mapping.append({"source": source, "destination": destination, "transform": "exact_copy", **pin(raw)})
        return raw, row

    closed = BASE / "native-validation-results/r31-start-closed"
    local_bytes = (closed / "LOCAL-READBACK.json").read_bytes()
    assert len(local_bytes) == 6536 and pin(local_bytes)["sha256"] == "6817099cb5d8b752798dbc4bc2b7fdef431e574a0d8bdf8b61fe54d2bded9fb8"
    local = json.loads(local_bytes)
    for entry in local["files"]:
        copy("native-validation-results/r31-start-closed/" + entry["path"],
             "input/r31-start/" + entry["path"], {key: entry[key] for key in ("bytes", "sha256", "git_blob")})
    copy("native-validation-results/r31-start-closed/LOCAL-READBACK.json", "input/r31-start/LOCAL-READBACK.json")
    copy("source53-r31-root-review/ROOT-EXECUTION-AUTHORIZATION.json", "input/ROOT-R31-EXECUTION-AUTHORIZATION.json",
         {"bytes": 2069, "sha256": "f97eda581ff5bb65797e2c483466305d8f881de51ac18256777e7f71ba0455ad"})
    copy("source53-apply-preparation/derived/native-candidate-r30-source.json", "input/native-candidate-r30-source.json",
         {"bytes": 56747, "sha256": "9292bd9002716a0bec35ecea294f9dfef3dbb1e9c1d8fe66660e502aecc5cdda"})
    copy("source53-apply-preparation/references/source52-actual-manifest.json", "input/source52-parent-manifest.json",
         {"bytes": 55209, "sha256": "3ff99b41bab572666b424fdbf9a508b33be13e6487d9effa7dd6a0e14b4ec898"})

    info = json.loads((HERE / "transport/scope-file-info-original.json").read_bytes())
    assert info == local["scope_file_info"]
    position = 0
    parts = []
    chunk_rows = []
    for i in range(2):
        name = f"transport/scope-chunk-{i}-original.json"
        chunk = json.loads((HERE / name).read_bytes())
        raw = base64.b64decode(chunk["data_base64"], validate=True)
        assert chunk["path"] == info["path"] and chunk["version"] == info["version"]
        assert chunk["size"] == info["size"] and chunk["offset"] == position
        assert len(raw) == chunk["next_offset"] - chunk["offset"]
        assert pin(raw)["sha256"] == chunk["chunk_sha256"]
        assert chunk["eof"] is (i == 1)
        position = chunk["next_offset"]
        parts.append(raw)
        chunk_rows.append({"transport_original": name, "offset": chunk["offset"],
                           "next_offset": position, **pin(raw)})
    scope_bytes = b"".join(parts)
    assert position == len(scope_bytes) == info["size"] == 93425
    assert pin(scope_bytes)["sha256"] == info["sha256"] == "bb3fd5a19ef48a929058d66430b09654d4ab3cf36924a223b4dc32cef7faf533"
    scope_pin = put("input/native-workspace-r31-scope.json", scope_bytes)
    mapping.append({"source": info["path"], "destination": scope_pin["path"],
                    "transform": "two_version_pinned_binary_read_chunks", "version": info["version"], **pin(scope_bytes)})

    cache_path = "native-validation-results/r29-archive-closed/original/evidence/native-workspace-r29-metadata.json"
    metadata_bytes = (BASE / cache_path).read_bytes()
    metadata_info = json.loads((closed / "transport/metadata_info-original.json").read_bytes())
    receipt = json.loads((closed / "evidence/native-workspace-r31-metadata-receipt.json").read_bytes())
    assert metadata_info == local["metadata_file_info"]
    assert pin(metadata_bytes) == receipt["stdout"]
    assert len(metadata_bytes) == metadata_info["size"] == 937659
    assert pin(metadata_bytes)["sha256"] == metadata_info["sha256"] == "b29d6b0c49c63d6345f50597873e3fa98c79ea0cbfe923ae3dd700b5cc08af8d"
    compressed = gzip.compress(metadata_bytes, compresslevel=9, mtime=0)
    assert gzip.decompress(compressed) == metadata_bytes
    metadata_pin = put("input/native-workspace-r31-metadata.json.gz", compressed)
    mapping.append({"source": cache_path, "destination": metadata_pin["path"],
                    "transform": "deterministic_gzip_mtime_0_of_exact_same_hash_cached_bytes",
                    "original_uncompressed": pin(metadata_bytes), "stored": pin(compressed),
                    "fresh_native_origin": metadata_info,
                    "new_invocation_receipt": "input/r31-start/evidence/native-workspace-r31-metadata-receipt.json",
                    "does_not_relabel_old_r29_invocation": True})

    primary_bytes, _ = copy("source51-final-scope-readonly/PRIMARY-SOURCE-PINS.json", "input/unchanged-PRIMARY-SOURCE-PINS.json",
                            {"bytes": 13098, "sha256": "afc57e362890925d5628947a95dd1f719816996d0b26b2fef101dbcf827e7dd3"})
    primary = json.loads(primary_bytes)
    assert len(primary) == 34
    for row in primary:
        assert row["path"].startswith("original/")
        copy("source51-final-scope-readonly/" + row["path"], "input/primary/" + row["path"],
             {key: row[key] for key in ("bytes", "sha256", "git_blob")})
    copy("source51-final-scope-readonly/input/hepta-cell-framework-native.yml", "input/hepta-cell-framework-native.yml")

    function_sources = []
    for path, expected, names in (
        ("source53-r31-binding/native-run-r31.py", "2dc7b84b7dad0d6e150817e0dfc4105c4bb4d343103aacef0fb932eab698a6f9", ["capture_metadata"]),
        ("source53-finalize-preparation/native-finalize-source53-template.py", "41c18849f6ebd24b17695051ee9c1c47c38ae207f87bf6c004f76248210fa22d", ["load_final_scope", "verify_default_format_selection", "frozen_context_check"]),
    ):
        raw = (BASE / path).read_bytes()
        assert pin(raw)["sha256"] == expected
        text = raw.decode()
        tree = ast.parse(text)
        functions = {node.name: ast.get_source_segment(text, node)
                     for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names}
        assert set(functions) == set(names)
        function_sources.append({"original_path": path, **pin(raw), "functions": functions,
                                 "imported_or_executed": False})
    put("references/PRODUCER-CONSUMER-FUNCTIONS.json", encode(function_sources))
    put("INPUT-SOURCE-MAPPING.json", encode({"schema": "hepta.source53-r31-scope-input-mapping.v1", "files": mapping}))
    put("TRANSFER-READBACK.json", encode({
        "schema": "hepta.source53-r31-scope-transfer-readback.v1",
        "source_commit": "f74be175de66a4b351cd239d39d98cd34fe9cc1b",
        "source_tree": "440d4a8e09af4009e4d9ea067388826308da8803",
        "job_id": "1a1b275ba33-fc05-7e17", "scope": scope_pin,
        "scope_file_info": info, "scope_chunks": chunk_rows,
        "metadata_compressed": metadata_pin, "metadata_uncompressed": pin(metadata_bytes),
        "metadata_fresh_file_info": metadata_info, "metadata_cached_byte_source": cache_path,
        "metadata_new_native_invocation_preserved": True,
        "metadata_byte_cache_reuse_only": True, "old_r29_invocation_not_relabelled": True,
        "all_start_snapshot_originals_preserved": len(local["files"]),
        "native_test_log_read": False, "native_command_executed": False,
        "workspace_terminal_status": None, "workspace_pass_claimed": False,
        "fix_fmt_authorized": False, "primary_pins_bytes_unchanged": True,
    }))
    print(json.dumps({"scope": scope_pin, "metadata": metadata_pin, "inputs": len(mapping)}))


if __name__ == "__main__":
    main()
