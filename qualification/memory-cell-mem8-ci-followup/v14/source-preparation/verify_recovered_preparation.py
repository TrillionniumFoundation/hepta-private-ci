#!/usr/bin/env python3
"""Verify retained original preparation bytes, distinguishing missing originals."""
import base64
import datetime
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parent

def sha(b):
    return hashlib.sha256(b).hexdigest()

def blob(b):
    return hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()

def check(b, r):
    assert len(b) == r["bytes"] and sha(b) == r["sha256"] and blob(b) == r["git_blob"]

pub = json.loads((ROOT / "PUBLICATION.json").read_text())
chunks = []
for n, row in enumerate(pub["parts"], 1):
    wrapper = ROOT / f"PART_READBACK_{n}.json"
    if wrapper.exists():
        record = json.loads(wrapper.read_text())
        assert record["encoding"] == "base64" and record["sha"] == row["git_blob"]
        chunk = base64.b64decode("".join(record["content"].splitlines()), validate=True)
    else:
        chunk = (ROOT / f"source-preparation.tar.xz.part{n:02}").read_bytes()
    check(chunk, row)
    assert row["offset"] == sum(map(len, chunks))
    chunks.append(chunk)
raw = b"".join(chunks)
check(raw, pub["archive"])
assert len(raw) == 728468 and sha(raw) == "1d96a60b0d5e7bec25a80f97d3a8ed128df9e3c2f6c5a6fcd9738d8e301a2284"
manifest_raw = (ROOT / "MANIFEST.json").read_bytes()
check(manifest_raw, pub["member_manifest"])
manifest = json.loads(manifest_raw)
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as t:
    members = t.getmembers()
    assert len(members) == len({x.name for x in members}) == 28
    assert all(x.isfile() and not PurePosixPath(x.name).is_absolute() and ".." not in PurePosixPath(x.name).parts and "\\" not in x.name for x in members)
    data = {x.name: t.extractfile(x).read() for x in members}
assert data["MEMBER_MANIFEST.json"] == manifest_raw
assert set(data) == {r["name"] for r in manifest["members"]} | {"MEMBER_MANIFEST.json"}
for row in manifest["members"]:
    check(data[row["name"]], row)
observations = json.loads(data["v4/REMOTE_UPLOAD_OBSERVATIONS.json"])
input4_raw = base64.b64decode(observations["binary_write"]["request"]["data_base64"], validate=True)
check(input4_raw, pub["frozen_V4_input_embedded_losslessly"])
input5_raw = data["v5/INPUT_SOURCE_GATES.json.xz"]
assert len(input5_raw) == 333228 and sha(input5_raw) == "948e8c9ff924317f55feaa45a0c9bac92c29196f6bf652a888ddf7c8795bb0d0"
v4 = json.loads(lzma.decompress(input4_raw))
v5 = json.loads(lzma.decompress(input5_raw))
assert len(v4["files"]) == 101 and len(v5["files"]) == 103
for record in [v4, v5]:
    assert len(record["files"]) == len({r["path"] for r in record["files"]})
    for r in record["files"]:
        b = r["content"].encode()
        assert len(b) == r["bytes"] and sha(b) == r["sha256"] and blob(b) == r["input_git_blob"]
old_rows = {r["path"]: r for r in v4["files"]}
new_rows = {r["path"]: r for r in v5["files"]}
assert all(new_rows[k] == v for k, v in old_rows.items())
assert set(new_rows) - set(old_rows) == {"codex-rs/hepta-intelligence-eval/src/durable_holdout.rs", "codex-rs/hepta-intelligence-eval/src/durable_holdout_tests.rs"}
pins = {
    "v4/run_source_gates.py": (20848, "a7c1ee335dba00ad47adaed9bbe1a9e35fc69616fa99f0cd5af309edffcb0a86"),
    "ci/driver-v4/mem8_source_gates_v4.py": (23280, "90d3a98e4b13c80a7da334a854b50607496abf841c80e7f4cd106006e43fc354"),
    "ci/driver-v5/mem8_source_gates_v5.py": (23280, "f32ca75f21c2097a30bda5892606aef80c62e4072837de7e99e42b56b17cfcf9"),
    "ci/workflow-v5-original/mem8-source-gates-v5.yml": (9280, "95c7ce5ca5c52555579a026be02d94e78065ac6657b0503e181edf37fd18c2db"),
    "ci/workflow-v5-revision2/mem8-source-gates-v5.yml": (9499, "0190e2b3dfe210e2be5c7531c0a560e0e2716c98ce6057840fcffef958925990"),
    "ci/driver-v5/CI_PUBLICATION_RECEIPTS.json": (21152, "41a67930d3745ece306d653f7a5fbfa3f7bf5c3ad2475d2d0b11fb7e4be266f9"),
}
for name, (size, digest) in pins.items():
    assert len(data[name]) == size and sha(data[name]) == digest
assert observations["driver_upload_requests"] == 0 and observations["source_process_start_requests"] == 0
assert pub["original_artifact_recovery_complete"] is False
assert len(pub["missing_requested_original_files"]) == manifest["missing_requested_original_file_count"] == 15
assert all(r["status"] == "ORIGINAL_FILE_NOT_RECOVERED_AFTER_WORKSPACE_RESET" and r["path"] not in data for r in pub["missing_requested_original_files"])
report = {"schema": "hepta.mem8.preparation.root-readback-audit.v1", "verified_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "staged_commit": "947bf2cffedff659d543513f4a88ba432d11bd79", "full_binary_parts_verified": 2, "archive_bytes": len(raw), "archive_sha256": sha(raw), "archive_git_blob_computed": blob(raw), "whole_archive_blob_created": False, "regular_members_verified": 28, "exact_lossless_embedded_V4_input_verified": True, "V4_full_rows_verified": 101, "V5_full_rows_verified": 103, "all_101_V4_rows_unchanged_in_V5": True, "exact_drivers_verified": 3, "exact_workflows_verified": 2, "original_V4_source_process_requests": 0, "original_lost_preparation_file_count": 15, "original_artifact_recovery_complete": False, "known_hash_does_not_restore_lost_original": True, "new_native_or_model_requests": 0, "archive_supplied_code_executed": False, "status": "RETAINED_BYTES_AND_EXPLICIT_GAPS_VERIFIED", "limit": "Exact recovery of source inputs, drivers and primary receipts is not complete recovery of all preparation files or a full owner/effect cold recovery."}
(ROOT / "ROOT_READBACK_AUDIT.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
