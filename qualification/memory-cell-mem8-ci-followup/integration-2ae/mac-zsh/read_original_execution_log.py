"""Read the original compact execution log; emit only the selected test's PATH.

Wire fields are pinned to bazelbuild/bazel@9.3.0 src/main/protobuf/spawn.proto.
No archived command is executed, and no other environment value is emitted.
"""
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile
import zstandard

ZIP = "bazel-execution-logs-test-aarch64-apple-darwin-13838015751.zip"
ZIP_SHA = "7731d0837a1597aadc19ea6d69f167f372c9bebe37e79631fb0f7b96ad9e9af0"
MEMBER = "execution-log-test-test-1436.zst"
TARGET = "//codex-rs/core:core-all-test"
MAX_MESSAGE = 32 * 1024 * 1024
MAX_DECOMPRESSED = 1024 * 1024 * 1024

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def varint(data, pos=0):
    result = 0
    for shift in range(0, 70, 7):
        assert pos < len(data), "truncated varint"
        byte = data[pos]
        pos += 1
        result |= (byte & 127) << shift
        if not byte & 128:
            return result, pos
    raise ValueError("overlong varint")

def fields(data):
    pos = 0
    result = {}
    while pos < len(data):
        key, pos = varint(data, pos)
        number, wire = key >> 3, key & 7
        assert number > 0
        if wire == 0:
            value, pos = varint(data, pos)
        elif wire == 2:
            size, pos = varint(data, pos)
            assert size <= len(data) - pos
            value = data[pos:pos + size]
            pos += size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            assert size <= len(data) - pos
            value = data[pos:pos + size]
            pos += size
        else:
            raise ValueError("unsupported protobuf wire type")
        result.setdefault(number, []).append(value)
    return result

def one(mapping, key, default=None):
    values = mapping.get(key, [])
    assert len(values) <= 1, "duplicate scalar field"
    return values[0] if values else default

def text(mapping, key, default=b""):
    return one(mapping, key, default).decode("utf-8")

def main(directory):
    directory = Path(directory)
    raw = (directory / ZIP).read_bytes()
    assert len(raw) == 10855234 and sha(raw) == ZIP_SHA
    proto = (directory / "spawn-bazel-9.3.0.proto").read_bytes()
    assert hashlib.sha1(b"blob " + str(len(proto)).encode() + b"\0" + proto).hexdigest() == "19f68f22a4d62c4fd1aa28fd1c7c0217aa6a7cb0"
    metadata = json.loads((directory / "ARTIFACT_METADATA.json").read_text())
    assert metadata["id"] == 13838015751
    assert metadata["workflow_run"]["id"] == 42971470498
    assert metadata["workflow_run"]["head_sha"] == "2ae5215beaf8d7b7df111a090b82134beae2683d"
    assert metadata["digest"] == "sha256:" + ZIP_SHA
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.namelist() == [MEMBER]
        compressed = archive.read(MEMBER)
    assert len(compressed) == 10857694
    rows, invocation, record_count, decoded = [], None, 0, 0
    all_spawn_count = 0
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(compressed)) as stream:
        while True:
            first = stream.read(1)
            if not first:
                break
            header = bytearray(first)
            while header[-1] & 128:
                assert len(header) < 10
                byte = stream.read(1)
                assert byte
                header += byte
            length, _ = varint(header)
            assert length <= MAX_MESSAGE
            decoded += len(header) + length
            assert decoded <= MAX_DECOMPRESSED
            body = bytearray()
            while len(body) < length:
                part = stream.read(length - len(body))
                assert part, "truncated compact entry"
                body += part
            body = bytes(body)
            record_count += 1
            entry = fields(body)
            if 2 in entry:
                assert record_count == 1 and invocation is None
                inv = fields(one(entry, 2))
                invocation = {"id": text(inv, 4), "hash_function": text(inv, 1), "workspace": text(inv, 2)}
            if 7 not in entry:
                continue
            all_spawn_count += 1
            spawn = fields(one(entry, 7))
            label = text(spawn, 7)
            if not label.endswith(TARGET) or text(spawn, 8) != "TestRunner":
                continue
            path_values = []
            for encoded_env in spawn.get(2, []):
                env = fields(encoded_env)
                if one(env, 1, b"") == b"PATH":
                    path_values.append(text(env, 2))
            assert len(path_values) == 1, "selected test action must have exactly one PATH"
            args = spawn.get(1, [])
            digest = fields(one(spawn, 16, b""))
            row = {
                "compact_record_ordinal": record_count,
                "entry_id": one(entry, 1, 0),
                "entry_sha256": sha(body),
                "target_label": label,
                "mnemonic": text(spawn, 8),
                "exit_code": one(spawn, 9, 0),
                "runner": text(spawn, 11),
                "cache_hit": bool(one(spawn, 12, 0)),
                "action_digest_hash": text(digest, 1),
                "args_count": len(args),
                "argv_markers": [
                    {"index": index, "basename": arg.rsplit(b"/", 1)[-1].decode()}
                    for index, arg in enumerate(args)
                    if arg.rsplit(b"/", 1)[-1] in (b"test-setup.sh", b"generate-xml.sh")
                ],
                "args_sha256": sha(b"\0".join(args)),
                "PATH": path_values[0],
            }
            rows.append(row)
    assert invocation and invocation["id"] == "d2fec41d-b448-48ad-b477-637d62508154"
    assert rows, "no selected original test actions"
    main_rows = [row for row in rows if row["argv_markers"] == [{"index": 0, "basename": "test-setup.sh"}]]
    auxiliary_rows = [row for row in rows if row["argv_markers"] == [{"index": 0, "basename": "generate-xml.sh"}]]
    assert len(main_rows) == len(auxiliary_rows) == 29
    assert len(main_rows) + len(auxiliary_rows) == len(rows)
    assert all(row["runner"] == "local" and not row["cache_hit"] for row in main_rows)
    assert sum(row["exit_code"] == 101 for row in main_rows) == 19
    assert sum(row["exit_code"] == 0 for row in main_rows) == 10
    return {
        "schema": "mem8.mac-arm.original-bazel-core-path.v3",
        "artifact_id": 13838015751, "workflow_run_id": 42971470498,
        "zip_bytes": len(raw), "zip_sha256": sha(raw),
        "member": {"path": MEMBER, "bytes": len(compressed), "sha256": sha(compressed)},
        "schema_source": {"repository": "bazelbuild/bazel", "ref": "9.3.0", "path": "src/main/protobuf/spawn.proto", "git_blob": "19f68f22a4d62c4fd1aa28fd1c7c0217aa6a7cb0"},
        "invocation": invocation, "complete_stream_read": True,
        "decoded_bytes": decoded, "compact_records": record_count,
        "all_spawn_records_count": all_spawn_count,
        "selected_test_runner_spawn_records": len(rows),
        "main_test_actions": len(main_rows), "auxiliary_xml_actions": len(auxiliary_rows),
        "main_test_exit_counts": {"0": 10, "101": 19},
        "path_values": sorted({row["PATH"] for row in rows}), "actions": rows,
        "limits": ["PATH is the original Bazel TestRunner action environment; it does not observe the later zsh child environment or its startup scripts.", "No other environment values, commands, or source contents are projected.", "Original exit codes and cache flags are observations, not a new execution or repaired-head qualification."],
        "new_native_commands": 0, "new_model_requests": 0,
    }

if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1]), indent=2, sort_keys=True))
