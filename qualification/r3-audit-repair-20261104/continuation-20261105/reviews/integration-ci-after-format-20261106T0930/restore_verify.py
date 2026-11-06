#!/usr/bin/env python3
"""Restore the immutable evidence and rerun only its Python API verifier."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile


def identity(raw):
    return {"bytes": len(raw), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), "restore output must not exist"
    manifest = json.loads((args.root / "member-manifest.json").read_bytes())
    metadata = json.loads((args.root / "archive.json").read_bytes())
    pieces = []
    for part in metadata["parts"]:
        encoded = (args.root / part["path"]).read_bytes()
        assert identity(encoded) == {k: part[k] for k in ["bytes", "git_blob", "sha256"]}
        pieces.append(encoded.strip())
    raw = base64.b64decode(b"".join(pieces), validate=True)
    assert identity(raw) == metadata["archive"]
    expected = {m["path"]: m for m in manifest["members"]}
    assert len(expected) == len(manifest["members"])
    args.output.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as tar:
        members = tar.getmembers()
        assert len(members) == len(expected)
        assert {m.name for m in members} == set(expected)
        for member in members:
            name = PurePosixPath(member.name)
            assert member.isfile() and not name.is_absolute() and ".." not in name.parts
            data = tar.extractfile(member).read()
            assert identity(data) == {k: expected[member.name][k] for k in ["bytes", "git_blob", "sha256"]}
            target = args.output.joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    run = subprocess.run(["python3", str(args.output / "verify_ci.py"), "--root", str(args.output)], capture_output=True)
    assert run.returncode == 0 and run.stderr == b"", {"exit": run.returncode, "stderr": run.stderr.decode(errors="replace")}
    assert run.stdout == (args.output / "verification-02.stdout.json").read_bytes()
    print(json.dumps({"archive": identity(raw), "members": len(expected), "member_bytes": sum(x["bytes"] for x in expected.values()), "verification_exit": run.returncode, "verification_stdout": identity(run.stdout), "verification_stderr_bytes": len(run.stderr), "originals_unchanged": True, "network_calls": 0, "native_product_execution": False}, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
