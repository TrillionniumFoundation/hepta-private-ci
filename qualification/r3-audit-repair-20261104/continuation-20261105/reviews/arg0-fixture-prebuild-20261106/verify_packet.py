#!/usr/bin/env python3
"""Restore exact packet bytes and replay offline author controls; no product toolchain."""
import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import shutil


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("packet", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--old-terminal-originals", type=Path)
args = parser.parse_args()
packet, output = args.packet.resolve(), args.output.resolve()
assert not output.exists()
index = json.loads((packet / "packet-index.json").read_bytes())
manifest_bytes = (packet / "manifest.json").read_bytes()
assert identity(manifest_bytes) == index["manifest"]
manifest = json.loads(manifest_bytes)
chunks = []
for part in index["parts"]:
    encoded = (packet / part["path"]).read_bytes()
    assert identity(encoded) == {k: part[k] for k in identity(encoded)}
    decoded = base64.b64decode(encoded.strip(), validate=True)
    assert len(decoded) == part["decoded_bytes"] and hashlib.sha256(decoded).hexdigest() == part["decoded_sha256"]
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
for entry in manifest["members"]:
    data = members["root/" + entry["path"]]
    assert identity(data) == {k: entry[k] for k in identity(data)}
    path = output / "root" / entry["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o644)
restored = output / "root"
command = [sys.executable, str(restored / "verify_candidate.py"), "--source", str(restored), "--output", str(output / "author-replay")]
proc = subprocess.run(command, capture_output=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
(output / "author-replay.stdout.original.json").write_bytes(proc.stdout)
(output / "author-replay.stderr.original.txt").write_bytes(proc.stderr)
assert proc.returncode == 0 and not proc.stderr, proc.stderr.decode(errors="replace")
assert identity(proc.stdout) == index["author_stdout"]
assert proc.stdout == (restored / "verification-final.stdout.json").read_bytes()
for name in ("full.patch", "source-map.json", "intended-full-tree.json", "VERIFICATION.json"):
    assert (output / "author-replay" / name).read_bytes() == (restored / name).read_bytes()
review_root = restored / "independent-review"
for entry in json.loads((restored / "FREEZE.json").read_bytes())["files"]:
    path = review_root / "frozen-author" / entry["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(restored / entry["path"], path)
review_run = subprocess.run([sys.executable, str(review_root / "verify_independent.py"), "--root", str(review_root)], capture_output=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
(output / "independent-replay.stdout.original.json").write_bytes(review_run.stdout)
(output / "independent-replay.stderr.original.txt").write_bytes(review_run.stderr)
assert review_run.returncode == 0 and not review_run.stderr
assert review_run.stdout == (review_root / "INDEPENDENT_VERIFICATION.stdout.json").read_bytes()
historical = {"status": "NOT_REPLAYED_WITHOUT_EXTERNAL_ORIGINALS", "registry_actual": index["external_old_terminal_registry_actual"]}
if args.old_terminal_originals:
    command = [sys.executable, str(restored / "applicability/verify_applicability.py"), str(restored / "applicability"), str(args.old_terminal_originals.resolve())]
    check = subprocess.run(command, capture_output=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    (output / "applicability-replay.stdout.original.json").write_bytes(check.stdout)
    (output / "applicability-replay.stderr.original.txt").write_bytes(check.stderr)
    assert check.returncode == 0 and not check.stderr
    assert identity(check.stdout) == index["applicability_stdout"]
    assert check.stdout == (restored / "applicability/verification-02.stdout.json").read_bytes()
    historical = {"status": "REPLAYED_EXISTING_EVIDENCE_ONLY", "exit_code": 0, "stdout_exact_equal": True, "stdout": identity(check.stdout), "registry_actual": index["external_old_terminal_registry_actual"]}
print(json.dumps({"schema": "arg0-fixture-prebuild-portable-replay-v1", "archive": index["archive"], "members": manifest["count"], "bytes": manifest["total_bytes"], "all_member_identities_equal": True, "author_replay": {"exit_code": 0, "stderr_bytes": 0, "stdout": identity(proc.stdout), "stdout_exact_equal": True, "four_derived_files_exact_equal": True}, "independent_static_replay": {"exit_code": 0, "stderr_bytes": 0, "stdout": identity(review_run.stdout), "stdout_exact_equal": True}, "historical_applicability": historical, "scope": "Offline synthetic controls and existing evidence replay; no new Cargo/Rust/native/CI/ref/PR action"}, indent=2, sort_keys=True))
