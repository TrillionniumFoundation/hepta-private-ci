#!/usr/bin/env python3
"""Verify original evidence bytes without extracting or executing archive contents."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_name(name):
    path = PurePosixPath(name)
    return (
        isinstance(name, str)
        and bool(name)
        and not path.is_absolute()
        and ".." not in path.parts
        and "." not in path.parts
        and "\\" not in name
        and path.as_posix() == name
    )


def verify_one(path, spec):
    label = spec["id"]
    require(path.is_file() and not path.is_symlink(), f"{label}: regular archive required")
    count = 0
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            count += len(chunk)
            sha.update(chunk)
    require(count == spec["bytes"], f"{label}: archive size mismatch")
    require(sha.hexdigest() == spec["sha256"], f"{label}: archive hash mismatch")
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        require(len(members) == spec["regular_members"], f"{label}: member count")
        require(all(m.isfile() and safe_name(m.name) for m in members), f"{label}: unsafe member")
        names = {m.name: m for m in members}
        require(len(names) == len(members), f"{label}: duplicate member")
        manifest_spec = spec["internal_manifest"]
        require(manifest_spec["path"] in names, f"{label}: manifest missing")
        require(names[manifest_spec["path"]].size == manifest_spec["bytes"], f"{label}: manifest size")
        manifest_raw = archive.extractfile(manifest_spec["path"]).read()
        require(digest(manifest_raw) == manifest_spec["sha256"], f"{label}: manifest hash")
        manifest = json.loads(manifest_raw)
        require(manifest["schema"] == manifest_spec["schema"], f"{label}: manifest schema")
        files = manifest["files"]
        require(manifest["file_count"] == len(files) == spec["payload_files"], f"{label}: payload count")
        expected = {}
        for item in files:
            require(safe_name(item["path"]), f"{label}: unsafe manifest path")
            name = spec["member_prefix"] + item["path"]
            require(name not in expected, f"{label}: duplicate manifest path")
            expected[name] = item
        require(set(names) == set(expected) | {manifest_spec["path"]}, f"{label}: required member set")
        total = 0
        for name, item in expected.items():
            require(names[name].size == item["bytes"], f"{label}: payload member size")
            raw = archive.extractfile(name).read()
            require(digest(raw) == item["sha256"], f"{label}: payload member hash")
            total += len(raw)
        require(total == spec["payload_bytes"], f"{label}: payload total size")
    return {
        "id": label,
        "bytes": count,
        "sha256": sha.hexdigest(),
        "verified_payload_files": len(expected),
        "verified_payload_bytes": total,
        "verified_regular_members": len(members),
    }


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, default=root / "archives/original-receipts.tar.gz")
    parser.add_argument("--auxiliary", type=Path, default=root / "archives/independent-reviews.tar.gz")
    args = parser.parse_args()
    source = root / "ARCHIVE_MANIFEST.json"
    manifest_raw = source.read_bytes()
    manifest = json.loads(manifest_raw)
    require(manifest["schema"] == "hepta-engineering-archive-custody-inputs:v1", "input schema")
    specs = {item["id"]: item for item in manifest["archives"]}
    require(set(specs) == {"original", "auxiliary"} and len(manifest["archives"]) == 2, "input set")
    result = {
        "schema": "hepta-engineering-archive-local-byte-verification:v1",
        "status": "passed",
        "scope": "full archive and direct member byte identity only; no archived code execution",
        "remote_readback_performed": False,
        "verifier_sha256": digest(Path(__file__).read_bytes()),
        "archive_manifest_sha256": digest(manifest_raw),
        "archives": [verify_one(args.original, specs["original"]), verify_one(args.auxiliary, specs["auxiliary"])],
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
