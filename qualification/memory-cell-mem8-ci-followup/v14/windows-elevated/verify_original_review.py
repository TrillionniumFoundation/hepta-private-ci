#!/usr/bin/env python3
"""Verify full original elevated review bytes and decode the 12 original ACLs."""
import base64
import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import tarfile

ROOT = Path(__file__).resolve().parent

def sha(b):
    return hashlib.sha256(b).hexdigest()

def blob(b):
    return hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()

def check(b, r):
    assert len(b) == r["bytes"] and sha(b) == r["sha256"] and blob(b) == r["git_blob"]

if (ROOT / "ARCHIVE_READBACK.json").exists():
    response = json.loads((ROOT / "ARCHIVE_READBACK.json").read_text())
    assert response["encoding"] == "base64" and response["sha"] == "8f83ef014873388d99d2e6adfb2018410efc8d2c"
    raw = base64.b64decode("".join(response["content"].splitlines()), validate=True)
else:
    raw = (ROOT / "ORIGINAL_SOURCE_REVIEW.tar.xz").read_bytes()
pub = json.loads((ROOT / "PUBLICATION.json").read_text())
check(raw, pub["archive"])
assert len(raw) == 79280 and sha(raw) == "0d1649c76b76fa3899cfdd3dda4c91862b1be9949a2878fd13a35c6abe09973a"
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as t:
    entries = t.getmembers()
    assert len(entries) == len({x.name for x in entries}) == 30
    assert all(x.isfile() and not PurePosixPath(x.name).is_absolute() and ".." not in PurePosixPath(x.name).parts and "\\" not in x.name for x in entries)
    data = {x.name: t.extractfile(x).read() for x in entries}
manifest = json.loads(data["FILE_MANIFEST.json"])
check(data["FILE_MANIFEST.json"], pub["file_manifest"])
assert len(manifest["members"]) == 29
assert set(data) == {r["path"] for r in manifest["members"]} | {"FILE_MANIFEST.json"}
for r in manifest["members"]:
    check(data[r["path"]], r)
check(data["PRODUCT_CLOSURE_REVIEW.json"], pub["report"])
index = json.loads(data["SOURCE_INDEX.json"])
assert index["source_head"] == "189711e3563ea13a5328d52e99a286f082045b98"
assert len(index["sources"]) == 22
for r in index["sources"]:
    assert r["ref"] == index["source_head"]
    check(data["source/" + r["path"]], r)
log = data["original/sandbox-native-delete-routes.log"]
assert len(log) == 27138 and sha(log) == "b002b5f84f101847e3de893c7de810c024bb309fd7ca7397776f93400e514c5c"
lines = log.decode().splitlines()
acl_audit = json.loads(data["ORIGINAL_ACL_AUDIT.json"])
assert acl_audit["acl_object_count"] == 12 and acl_audit["unique_acl_sids"] == ["S-1-1-0"]
rows = acl_audit["observed_acls"]
assert len(rows) == 12
for r in rows:
    line = lines[r["raw_line"] - 1]
    assert "elevated-child-done" in line
    hexes = re.search(r"acl=\[([^]]+)\]", line).group(1)
    acl = bytes(int(s.strip(), 16) for s in hexes.split(","))
    assert len(acl) == r["acl_bytes"] == struct.unpack_from("<H", acl, 2)[0]
    count = struct.unpack_from("<H", acl, 4)[0]
    offset, decoded = 8, []
    for _ in range(count):
        typ, flags, size, mask = struct.unpack_from("<BBHI", acl, offset)
        assert typ in [0, 1] and size >= 16 and offset + size <= len(acl)
        sid_bytes = acl[offset + 8:offset + size]
        rev, subcount = sid_bytes[:2]
        assert len(sid_bytes) == 8 + subcount * 4
        authority = int.from_bytes(sid_bytes[2:8], "big")
        subs = struct.unpack_from("<" + "I" * subcount, sid_bytes, 8)
        sid = "S-" + "-".join(str(x) for x in [rev, authority, *subs])
        decoded.append({"type": typ, "flags": flags, "mask": mask, "mask_hex": hex(mask), "sid": sid})
        offset += size
    assert offset == len(acl) and decoded == r["aces"]
    assert all(x["sid"] == "S-1-1-0" for x in decoded)
outcomes = []
for label in ["ordinary-host-cmd-done", "elevated-child-done"]:
    matching = [s for s in lines if label in s and "after_release=" in s]
    assert len(matching) == 1
    actual = re.findall(r"route: (\w+), file_deleted: (true|false), directory_deleted: (true|false)", matching[0])
    assert actual == [("Neither", "false", "false"), ("TargetOnly", "true", "true"), ("ParentOnly", "true", "true"), ("Both", "true", "true")]
    outcomes.append({"label": label, "actual": actual})
report = {"schema": "hepta.mem8.elevated-delete.root-full-readback-audit.v1", "verified_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "staged_commit": "d9b5987a67bb110d2c013a5e1a379fb976c2db22", "archive_git_blob": blob(raw), "archive_bytes": len(raw), "archive_sha256": sha(raw), "safe_regular_members_verified": 30, "complete_exact_189_sources_verified": 22, "original_acl_objects_independently_decoded": 12, "all_ace_sids": ["S-1-1-0"], "original_outcomes_verified": outcomes, "source_report_read_in_full": True, "production_fix": False, "actual_child_token_query": "NOT_PRESENT_IN_ORIGINAL_EVIDENCE", "native_or_model_executions": 0, "qualification": "READ_ONLY_SOURCE_AND_ORIGINAL_ACL_REVIEW_ONLY", "remote_binary_readback": "Full path-based base64 readback now verified; the earlier fetch_blob UnicodeDecodeError remains recorded in the original publication receipt."}
(ROOT / "ROOT_READBACK_AUDIT.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
