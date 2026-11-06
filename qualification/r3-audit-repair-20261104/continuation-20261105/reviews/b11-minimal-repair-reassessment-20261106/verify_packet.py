#!/usr/bin/env python3
"""Restore a fixed evidence packet and replay only read-only Python evidence checks."""
import base64
import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}

packet = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
assert not out.exists(), "Choose a new output directory"
index = json.loads((packet / "packet-index.json").read_bytes())
manifest_bytes = (packet / "manifest.json").read_bytes()
assert identity(manifest_bytes) == index["manifest"]
manifest = json.loads(manifest_bytes)
chunks = []
for part in index["parts"]:
    encoded = (packet / part["path"]).read_bytes()
    assert identity(encoded) == {k: part[k] for k in identity(encoded)}
    decoded = base64.b64decode(encoded.strip(), validate=True)
    assert len(decoded) == part["decoded_bytes"]
    assert hashlib.sha256(decoded).hexdigest() == part["decoded_sha256"]
    chunks.append(decoded)
archive = b"".join(chunks)
assert identity(archive) == index["archive"]
members = {}
with tarfile.open(fileobj=io.BytesIO(gzip.decompress(archive)), mode="r:") as stream:
    for item in stream.getmembers():
        path = PurePosixPath(item.name)
        assert item.isfile() and not path.is_absolute() and ".." not in path.parts
        assert item.mode == 0o644 and item.name not in members
        members[item.name] = stream.extractfile(item).read()
assert len(members) == index["archive_member_count_including_manifest"]
assert members.pop("MANIFEST.json") == manifest_bytes
assert len(members) == manifest["count"] == len(manifest["members"])
assert set(members) == {"root/" + x["path"] for x in manifest["members"]}
assert sum(map(len, members.values())) == manifest["total_bytes"]
for item in manifest["members"]:
    data = members["root/" + item["path"]]
    assert identity(data) == {k: item[k] for k in identity(data)}
    dest = out / "root" / item["path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    dest.chmod(0o644)
restored = out / "root"
proofs = []
for checker in index["read_only_replays"]:
    run = subprocess.run([sys.executable, str(restored / checker["script"]), str(restored)],
                         capture_output=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    (out / (checker["name"] + ".stdout.json")).write_bytes(run.stdout)
    (out / (checker["name"] + ".stderr.txt")).write_bytes(run.stderr)
    assert run.returncode == checker["expected_exit"] == 0 and not run.stderr
    assert identity(run.stdout) == checker["stdout"]
    assert run.stdout == (restored / checker["frozen_stdout"]).read_bytes()
    proofs.append({"name": checker["name"], "exit_code": run.returncode, "stderr_bytes": len(run.stderr),
                   "stdout": identity(run.stdout), "stdout_exact_equal": True})
print(json.dumps({"schema": "hepta-b11-reassessment-v2-portable-replay", "archive": index["archive"],
                  "restored_original_members": manifest["count"], "restored_member_bytes": manifest["total_bytes"],
                  "all_member_identities_equal": True, "read_only_replays": proofs,
                  "scope": "Historical evidence/source replay only, not new native or CI. No product source/ref changes."},
                 ensure_ascii=False, sort_keys=True, indent=2))

