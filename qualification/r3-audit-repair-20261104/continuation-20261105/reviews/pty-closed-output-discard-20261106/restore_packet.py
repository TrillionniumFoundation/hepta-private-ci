#!/usr/bin/env python3
"""Restore the immutable author packet and optionally replay its static verifier."""
import argparse
import base64
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


def check(data, entry):
    current = identity(data)
    assert current == {k: entry[k] for k in current}, entry.get("path")


def restore(packet, output, replay):
    manifest = json.loads((packet / "manifest.json").read_text())
    pieces = []
    for row in manifest["parts"]:
        data = (packet / row["path"]).read_bytes()
        check(data, row)
        pieces.append(data)
    raw = base64.b64decode(b"".join(pieces), validate=True)
    assert len(raw) == manifest["archive"]["bytes"]
    assert hashlib.sha256(raw).hexdigest() == manifest["archive"]["sha256"]
    assert not output.exists(), "Output must be new; never overwrite existing evidence"
    expected = {row["path"]: row for row in manifest["members"]}
    assert len(expected) == len(manifest["members"])
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert len(z.infolist()) == len(expected)
        assert set(z.namelist()) == set(expected)
        for item in z.infolist():
            name = PurePosixPath(item.filename)
            assert not name.is_absolute() and all(p not in ("", ".", "..") for p in name.parts)
            assert not item.is_dir() and (item.external_attr >> 16) == 0o100644
            body = z.read(item)
            check(body, expected[item.filename])
            path = output.joinpath(*name.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
    check((output / "freeze-manifest.json").read_bytes(), manifest["original_author_freeze"])
    freeze = json.loads((output / "freeze-manifest.json").read_text())
    assert freeze["data_files"] == len(freeze["files"]) == len(expected) - 1
    assert {x["path"] for x in freeze["files"]} | {"freeze-manifest.json"} == set(expected)
    for row in freeze["files"]:
        check((output / row["path"]).read_bytes(), row)
    result = {"schema": "hepta-pty-portable-restoration-v1", "archive_sha256": manifest["archive"]["sha256"],
              "members": len(expected), "all_bytes_equal": True, "static_replay": None,
              "compile_native_or_formatter_executed": False}
    if replay:
        run = subprocess.run([sys.executable, str(output / "verify_candidate.py"), "--root", str(output)],
                             cwd=output, capture_output=True)
        assert run.returncode == 0 and run.stderr == b""
        check(run.stdout, manifest["expected_verifier_stdout"])
        assert run.stdout == (output / "static-final.stdout.json").read_bytes()
        result["static_replay"] = {"exit_code": 0, "stdout": identity(run.stdout), "stderr": identity(run.stderr)}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    print(json.dumps(restore(args.packet.resolve(), args.output.resolve(), args.replay), indent=2))
