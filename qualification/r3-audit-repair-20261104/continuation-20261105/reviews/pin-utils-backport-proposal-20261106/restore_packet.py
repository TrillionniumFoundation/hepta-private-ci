#!/usr/bin/env python3
"""Recover byte-exact source/provenance. Optional replay uses only Git/Python fixtures."""
from pathlib import Path, PurePosixPath
import argparse
import base64
import gzip
import hashlib
import io
import json
import subprocess
import tarfile


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument("--extract", type=Path, required=True)
    ap.add_argument("--replay", action="store_true")
    args = ap.parse_args()
    archive = json.loads((args.root / "archive.json").read_bytes())
    manifest_raw = (args.root / "manifest.json").read_bytes()
    assert identity(manifest_raw) == archive["payload_manifest"]
    manifest = json.loads(manifest_raw)
    encoded = []
    for part in archive["parts"]:
        data = (args.root / part["path"]).read_bytes()
        assert identity(data) == {k: part[k] for k in identity(data)} and len(data) <= 240000
        encoded.append(data)
    raw = base64.b64decode(b"".join(encoded), validate=True)
    assert identity(raw) == archive["archive"]
    files = {}
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(raw)), mode="r:") as tar:
        for entry in tar:
            path = PurePosixPath(entry.name)
            assert entry.isfile() and not path.is_absolute() and ".." not in path.parts
            assert entry.name not in files and entry.name.startswith("root/")
            files[entry.name] = tar.extractfile(entry).read()
    assert len(files) == archive["archive_member_count"] == len(manifest["files"])
    assert set(files) == {row["path"] for row in manifest["files"]}
    for row in manifest["files"]:
        assert identity(files[row["path"]]) == {k: row[k] for k in identity(b"")}
    assert sum(map(len, files.values())) == archive["payload_bytes"]
    args.extract.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        target = args.extract / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    source = args.extract / "root/v2/final-review"
    frozen = json.loads((source / "SOURCE-FREEZE.json").read_bytes())
    actual = json.loads((args.extract / "root/v2/source-registration/candidate-postimages.actual.json").read_bytes())
    assert actual["computed_full_candidate_tree"] == frozen["computed_candidate_tree"]
    for record in actual["records"]:
        data = (source / "candidate" / record["path"]).read_bytes()
        assert identity(data) == frozen["candidate_source_files"][record["path"]]
        assert identity(data) == {k: record[k] for k in identity(data)}
        get = json.loads((args.extract / "root/v2" / record["full_GET_original_relative_path"]).read_bytes())
        assert get["status"] == "fulfilled"
        assert get["value"]["result"]["structuredContent"]["content"].encode() == data
        assert record["actual_full_GET_complete_byte_equality"]
    original_freeze = json.loads((args.extract / "root/final-review/SOURCE-FREEZE.json").read_bytes())
    for path, expected in original_freeze["candidate_source_files"].items():
        assert identity((args.extract / "root/final-review/candidate" / path).read_bytes()) == expected
    assert original_freeze["computed_candidate_tree"] == "5138ffd7759b8ad24a6dd11d1a23d9bdace076dc"
    replay = None
    if args.replay:
        proc = subprocess.run(["python3", str(source / "verify_candidate.py"), "--root", str(source),
                               "--output", str(args.extract / "verification-output")], capture_output=True)
        (args.extract / "replay.stdout.original.txt").write_bytes(proc.stdout)
        (args.extract / "replay.stderr.original.txt").write_bytes(proc.stderr)
        replay = {"exit_code": proc.returncode, "stdout": identity(proc.stdout), "stderr": identity(proc.stderr),
                  "stdout_equal_frozen": proc.stdout == (source / "verification-02.stdout.original.txt").read_bytes()}
        assert proc.returncode == 0 and not proc.stderr and replay["stdout_equal_frozen"]
        for name in ["intended-full-tree.json", "static-verification.json", "pipeline-controls.json", "workspace-manifest.static-preview.toml"]:
            assert (args.extract / "verification-output" / name).read_bytes() == (source / "verification-v2" / name).read_bytes()
        replay["all_four_derived_outputs_equal"] = True
    print(json.dumps({"schema": "pin-utils-proposal-packet-verification-v1", "archive": archive["archive"],
        "members": len(files), "complete_payload_bytes": sum(map(len, files.values())),
        "source_full_GET_bindings": len(actual["records"]), "computed_candidate_tree": frozen["computed_candidate_tree"],
        "old_v1_frozen_source_preserved": True,
        "optional_offline_replay": replay, "actual_Cargo_Bazel_or_product_native_execution": False,
        "ref_publication": False}, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
