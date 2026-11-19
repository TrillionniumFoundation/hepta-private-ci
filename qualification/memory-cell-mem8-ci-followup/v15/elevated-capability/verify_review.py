#!/usr/bin/env python3
"""Verify frozen source bytes and the original ACL decode without running a test."""
import hashlib
import json
import re
import struct
from pathlib import Path

root = Path(__file__).resolve().parent
index = json.loads((root / "SOURCE_INDEX.json").read_text())
assert index["head"] == "9bd2f589debdba4a93baa363817c3669cb103721"
assert index["tree"] == "c77785ecb368c44ea699769001a47402c9f50591"
assert len(index["files"]) == 23
for row in index["files"]:
    data = (root / "source" / row["path"]).read_bytes()
    assert len(data) == row["bytes"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"]
    assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == row["git_blob"]
raw = (root / "sandbox-native-delete-routes.log").read_bytes()
assert len(raw) == 27138
assert hashlib.sha256(raw).hexdigest() == "0f4357942bd12783593f3d0a817d97db7ac3d26395a0bee30f5951ac5672976a"
observed = []
for number, line in enumerate(raw.decode().splitlines(), 1):
    if "delete_matrix elevated-child-done path=" not in line:
        continue
    match = re.search(r"acl=\[(.*)\]$", line)
    assert match
    data = bytes(int(item.strip(), 16) for item in match.group(1).split(","))
    revision, _, length, count, _ = struct.unpack_from("<BBHHH", data)
    assert revision == 2 and length == len(data)
    offset = 8
    aces = []
    for _ in range(count):
        kind, flags, size, mask = struct.unpack_from("<BBHI", data, offset)
        assert kind in (0, 1) and size >= 16
        sid = data[offset + 8:offset + size]
        assert sid[0] == 1 and len(sid) == 8 + 4 * sid[1]
        value = "S-1-" + str(int.from_bytes(sid[2:8], "big"))
        value += "".join("-" + str(struct.unpack_from("<I", sid, 8 + 4 * i)[0]) for i in range(sid[1]))
        assert value == "S-1-1-0"
        aces.append({"type": "allow" if kind == 0 else "deny", "flags": flags, "mask": mask, "sid": value})
        offset += size
    assert offset == len(data)
    observed.append({"line": number, "object_path_literal": re.search(r'path=(".*?") identity=', line).group(1), "acl_bytes": len(data), "acl_sha256": hashlib.sha256(data).hexdigest(), "aces": aces})
saved = json.loads((root / "CURRENT_ORIGINAL_ACL_AUDIT.json").read_text())
assert len(observed) == 12 and observed == saved["rows"]
print(json.dumps({"exact_source_files": 23, "original_acl_rows": 12, "all_checks": "PASS_READ_ONLY", "native_executions": 0}))
