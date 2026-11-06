#!/usr/bin/env python3
"""Restore immutable split archive and run its offline-only verification."""
import argparse
import base64
import hashlib
import io
import json
import lzma
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    definition = json.loads((args.root / "archive.json").read_bytes())
    manifest_bytes = (args.root / "member-manifest.json").read_bytes()
    assert identity(manifest_bytes) == definition["manifest"]
    manifest = json.loads(manifest_bytes)
    encoded = []
    for i, item in enumerate(definition["parts"]):
        assert item["path"] == f"archive-part-{i:03d}.b64"
        data = (args.root / item["path"]).read_bytes()
        assert identity(data) == {k: item[k] for k in ["bytes", "git_blob", "sha256"]}
        assert data.endswith(b"\n") and b"\n" not in data[:-1] and b"\r" not in data
        encoded.append(data[:-1])
    archive = base64.b64decode(b"".join(encoded), validate=True)
    assert identity(archive) == definition["archive_identity"]
    raw_tar = lzma.decompress(archive, format=lzma.FORMAT_XZ, memlimit=256 * 1024 * 1024)
    expected = {"root/" + item["path"]: item for item in manifest["members"]}
    assert len(expected) == len(manifest["members"]) == definition["members"] == manifest["count"]
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as tar:
        members = tar.getmembers()
        assert len(members) == len(expected) and {item.name for item in members} == set(expected)
        for member in members:
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and all(x not in ["", ".", ".."] for x in path.parts)
            body = tar.extractfile(member).read()
            item = expected[member.name]
            assert identity(body) == {k: item[k] for k in ["bytes", "git_blob", "sha256"]}
            dest = args.output.joinpath(*path.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            total += len(body)
    assert total == definition["member_bytes"] == manifest["member_bytes"]
    root = args.output / "root"
    command = [sys.executable, str(root / "verify_packet.py"), "--root", str(root)]
    result = subprocess.run(command, capture_output=True)
    (args.output / "replay.stdout.json").write_bytes(result.stdout)
    (args.output / "replay.stderr.txt").write_bytes(result.stderr)
    assert result.returncode == 0 and not result.stderr, (result.returncode, result.stderr.decode())
    assert result.stdout == (root / "verification-01.stdout.json").read_bytes()
    print(json.dumps({"schema": "hepta-portable-17-two-CI-cuts-replay-v1", "members": len(expected), "member_bytes": total, "archive": identity(archive), "offline_replay_exit": 0, "offline_replay_stderr_bytes": 0, "offline_replay_stdout": identity(result.stdout), "all_member_identities_equal": True, "replay_stdout_full_equal": True}, indent=2))


if __name__ == "__main__":
    main()
