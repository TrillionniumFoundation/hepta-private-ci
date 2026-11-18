#!/usr/bin/env python3
"""Reconcile retained archive bytes and every indexed original; run no models."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_bytes(raw, record, label):
    require(len(raw) == record["bytes"], label + ": size mismatch")
    require(hashlib.sha256(raw).hexdigest() == record["sha256"], label + ": hash mismatch")


def reconcile(directory):
    manifest = json.loads((directory / "ARCHIVE_PARTS.json").read_bytes())
    payloads = []
    for part in manifest["parts"]:
        name = part["path"]
        require(Path(name).name == name, "part must be a direct child")
        raw = (directory / name).read_bytes()
        verify_bytes(raw, part, name)
        require(len(raw) < 512000, "part exceeds the publication blob bound")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            require(archive.namelist() == ["payload.bin"], "unexpected ZIP contents")
            payload = archive.read("payload.bin")
        verify_bytes(payload, part["payload"], name + " payload")
        payloads.append(payload)
    raw = b"".join(payloads)
    verify_bytes(raw, manifest["archive"], "original gzip tar")
    index_raw = (directory / "INDEX.json").read_bytes()
    verify_bytes(index_raw, manifest["index"], "external original index")
    index = json.loads(index_raw)
    rows = {row["path"]: row for row in index["files"]}
    require(len(rows) == len(index["files"]) == index["member_count"], "duplicate index entry")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = archive.getmembers()
        require(len(members) == len(rows), "member count mismatch")
        require(len({member.name for member in members}) == len(rows), "duplicate archive member")
        require({member.name for member in members} == set(rows), "archive/index names differ")
        for member in members:
            path = PurePosixPath(member.name)
            require(member.isfile() and not path.is_absolute() and ".." not in path.parts,
                    "unsafe or non-regular member")
            verify_bytes(archive.extractfile(member).read(), rows[member.name], member.name)
    return raw, {
        "run": directory.name,
        "status": "ARCHIVE_AND_ALL_MEMBERS_RECONCILED",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "members": len(rows),
        "model_calls": 0,
        "semantic_verifier_calls": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-archives", type=Path,
                        help="create this new directory and write the two verified gzip tars")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / "raw"
    results = [(name, *reconcile(root / name)) for name in ("run-1", "run-2")]
    if args.write_archives is not None:
        args.write_archives.mkdir(parents=True, exist_ok=False)
        for name, raw, _ in results:
            with (args.write_archives / (name + ".tar.gz")).open("xb") as stream:
                stream.write(raw)
    print(json.dumps({"archives": [row for _, _, row in results]}, sort_keys=True))


if __name__ == "__main__":
    main()
