"""Verify this preparation packet without executing any candidate command."""

import argparse
import hashlib
import json
from pathlib import PurePosixPath
import tarfile


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("archive")
args = parser.parse_args()
with tarfile.open(args.archive, "r:xz") as archive:
    members = archive.getmembers()
    assert len({member.name for member in members}) == len(members)
    for member in members:
        path = PurePosixPath(member.name)
        assert member.isfile() and not path.is_absolute() and ".." not in path.parts
    contents = {member.name: archive.extractfile(member).read() for member in members}
manifest = json.loads(contents["FILE_MANIFEST.json"])
assert set(contents) == {row["path"] for row in manifest} | {"FILE_MANIFEST.json"}
for row in manifest:
    data = contents[row["path"]]
    assert len(data) == row["bytes"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"]
    assert blob(data) == row["git_blob"]
candidate = json.loads(contents["CANDIDATE_MANIFEST.json"])
capsule = json.loads(contents["SOURCE_CAPSULE.json"])
for row in candidate["rows"]:
    data = contents["source/" + row["path"]]
    assert row["preimage"] is None
    assert blob(data) == row["postimage"]["git_blob"]
    assert hashlib.sha256(data).hexdigest() == row["postimage"]["sha256"]
    assert next(x["content"] for x in capsule["files"] if x["path"] == row["path"]).encode() == data
index = json.loads(contents["SOURCE_INDEX.json"])
included_references = 0
for row in index["source_index"]:
    data = contents.get("reference/" + row["path"])
    if data is not None:
        assert len(data) == row["bytes"] and blob(data) == row["git_blob"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"]
        included_references += 1
assert included_references == 10
assert candidate["native_pass_prerequisite"] is False
assert candidate["source_head"] == "b0547d2f874c0aeb54dabd3491caa2bee49fcb0b"
assert candidate["source_tree"] == "3f89ddeff13d0af85f4abe2690699107357f1038"
assert json.loads(contents["MEM_CI_FINAL_HARNESS_PEER.json"])["result"] == "no_static_must_fix"
print(json.dumps({
    "status": "PASS_OFFLINE_PACKET_ONLY", "members": len(members),
    "candidate_postimages": len(candidate["rows"]), "exact_reference_files": included_references,
    "large_lock_references": "Immutable pins only; full lock bytes are not duplicated in this packet",
    "runtime_commands_executed": 0,
}, sort_keys=True))
