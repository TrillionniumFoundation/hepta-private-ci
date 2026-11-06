#!/usr/bin/env python3
"""Restore exact frozen B21 v3 bytes and optionally replay only evidence checks."""
import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


def file_identity(path):
    size = path.stat().st_size
    git = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1048576):
            git.update(chunk)
            sha.update(chunk)
    return {"bytes": size, "git_blob": git.hexdigest(), "sha256": sha.hexdigest()}


def check(actual, expected):
    assert actual == {key: expected[key] for key in actual}, expected.get("path")


def restore(packet, output, replay):
    manifest = json.loads((packet / "manifest.json").read_bytes())
    assert manifest["original_freeze"]["git_blob"] == "b94ccbf22bdeca017e740fcaed20e14f3e06113f"
    assert not output.exists(), "Output must be new; do not overwrite evidence"
    members = {row["path"]: row for row in manifest["members"]}
    assert len(members) == len(manifest["members"]) == 43
    with tempfile.TemporaryDirectory(prefix="b21-v3-readonly-restore-") as tmp:
        archive = Path(tmp) / "evidence.zip"
        seen_parts = set()
        with archive.open("xb") as dst:
            for row in manifest["parts"]:
                assert row["path"] not in seen_parts
                seen_parts.add(row["path"])
                part_name = PurePosixPath(row["path"])
                assert len(part_name.parts) == 1 and part_name.name not in ("", ".", "..")
                data = (packet / part_name.name).read_bytes()
                assert len(data) <= 400000
                check(identity(data), row)
                dst.write(base64.b64decode(data, validate=True))
        check(file_identity(archive), manifest["archive"])
        with zipfile.ZipFile(archive) as z:
            assert len(z.infolist()) == len(members) and set(z.namelist()) == set(members)
            for item in z.infolist():
                relative = PurePosixPath(item.filename)
                assert not relative.is_absolute() and all(p not in ("", ".", "..") for p in relative.parts)
                assert not item.is_dir() and (item.external_attr >> 16) == 0o100644
                path = output.joinpath(*relative.parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                with z.open(item) as src, path.open("xb") as dst:
                    shutil.copyfileobj(src, dst, 1048576)
                check(file_identity(path), members[item.filename])
    check(file_identity(output / "freeze-manifest.json"), manifest["original_freeze"])
    freeze = json.loads((output / "freeze-manifest.json").read_bytes())
    assert len(freeze["files"]) == freeze["members"] == 42
    assert sum(row["bytes"] for row in freeze["files"]) == freeze["total_bytes"] == 83441944
    assert {row["path"] for row in freeze["files"]} | {"freeze-manifest.json"} == set(members)
    for row in freeze["files"]:
        check(file_identity(output / row["path"]), row)
    result = {"schema": "hepta-b21-collector-v3-native-portable-restoration-v1",
              "archive": manifest["archive"], "parts": len(manifest["parts"]), "members": len(members),
              "all_frozen_bytes_equal": True, "read_only_replay": None,
              "product_native_or_CI_executed": False, "ledger_transition": "NONE; B21/B15 OPEN"}
    if replay:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        run = subprocess.run([sys.executable, "-B", str(output / "verify_native.py")], cwd=output,
                             env=env, capture_output=True, timeout=300, check=False)
        assert run.returncode == 0, f"Read-only verifier exit {run.returncode}"
        assert run.stderr == b"", "Read-only verifier emitted stderr"
        check(identity(run.stdout), manifest["expected_verifier_stdout"])
        assert run.stdout == (output / "verification.stdout.json").read_bytes()
        result["read_only_replay"] = {"exit_code": 0, "stdout": identity(run.stdout), "stderr": identity(run.stderr)}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    print(json.dumps(restore(args.packet.resolve(), args.output.resolve(), args.replay), indent=2))
