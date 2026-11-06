#!/usr/bin/env python3
"""Restore complete, exact serialized actual registration returns without network."""
import argparse
import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path, PurePosixPath


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


def check(data, expected):
    assert identity(data) == {key: expected[key] for key in ("bytes", "git_blob", "sha256")}


def safe_name(name):
    path = PurePosixPath(name)
    assert not path.is_absolute() and all(p not in ("", ".", "..") for p in path.parts)
    return path


def restore(packet, output):
    assert not output.exists(), "Receipt output must be a new directory"
    manifest = json.loads((packet / "registration-receipts.manifest.json").read_bytes())
    pieces = []
    for row in manifest["parts"]:
        name = safe_name(row["path"])
        assert len(name.parts) == 1
        data = (packet / row["path"]).read_bytes()
        assert len(data) <= 400000
        check(data, row)
        pieces.append(base64.b64decode(data, validate=True))
    archive = b"".join(pieces)
    check(archive, manifest["archive"])
    members = {row["path"]: row for row in manifest["members"]}
    assert len(members) == len(manifest["members"])
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert len(z.infolist()) == len(members) and set(z.namelist()) == set(members)
        for item in z.infolist():
            name = safe_name(item.filename)
            assert not item.is_dir() and (item.external_attr >> 16) == 0o100644
            data = z.read(item)
            check(data, members[item.filename])
            path = output.joinpath(*name.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    catalog = json.loads((output / "core-payload-catalog.json").read_bytes())
    bodies = {row["git_blob"]: row for row in catalog["unique_payloads"]}
    expected = {row["path"]: row for row in json.loads((output / "registration-raw-index.json").read_bytes())["files"]}
    observed = set()
    for path in sorted((output / "registration-recipes").glob("*.json")):
        batch = json.loads(path.read_bytes())
        for receipt in batch["receipts"]:
            raw = receipt["template"]
            if "payload_git_blob" in receipt:
                row = bodies[receipt["payload_git_blob"]]
                relative = safe_name(row["packet_path"])
                data = packet.joinpath(*relative.parts).read_bytes()
                check(data, row)
                body = data.decode("utf-8")
                assert raw.count(receipt["marker"]) == receipt["occurrences"]
                raw = raw.replace(receipt["marker"], json.dumps(body, ensure_ascii=False)[1:-1])
                result = json.loads(raw)
                assert result["isError"] is False and result["structuredContent"]["content"] == body
            name = "registration-raw/" + receipt["filename"]
            safe_name(name)
            assert name in expected and name not in observed
            observed.add(name)
            data = raw.encode("utf-8")
            check(data, expected[name])
            dest = output / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    assert observed == set(expected)
    assert len(observed) == manifest["actual_tool_return_count"] == 340
    return {"schema": "b21-v3-registration-originals-lossless-restoration-v1", "receipt_archive": manifest["archive"],
            "receipt_members": len(members), "complete_actual_tool_returns_restored": len(observed),
            "all_serialized_original_lengths_Git_SHA256_equal": True,
            "prior_lost_231_raw_returns_not_reconstructed": True,
            "new_post_recovery_GETs_distinguished_from_lost_history": True,
            "product_native_CI_or_refs_changed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore(args.packet.resolve(), args.output.resolve()), indent=2))
