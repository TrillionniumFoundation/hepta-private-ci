"""Restore the seven available library recovery archives without filling gaps."""

import argparse
import hashlib
import json
from pathlib import Path

from restore_raw_evidence import read_regular, read_verified, relative_path


MANIFEST = "research/library-recovery/STORAGE_MANIFEST.json"


def prepare(repo):
    manifest = json.loads(read_regular(repo, MANIFEST, 1024 * 1024))
    if manifest["schema"] != "hepta.library-recovery.exact-storage.v1":
        raise ValueError("unsupported library recovery storage schema")
    outputs = {}
    for row in manifest["files"]:
        name = relative_path(row["original_path"])
        if name in outputs:
            raise ValueError("duplicate original archive path")
        chunks = []
        total = 0
        for part in row["parts"]:
            data = read_verified(repo, part["path"], part["bytes"], part["sha256"])
            total += len(data)
            if total > row["original"]["bytes"] or total > 8 * 1024 * 1024:
                raise ValueError("archive parts exceed the original byte bound")
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if blob != part["git_blob"]:
                raise ValueError("original part Git blob mismatch")
            chunks.append(data)
        raw = b"".join(chunks)
        if len(raw) != row["original"]["bytes"]:
            raise ValueError("original archive length mismatch")
        if hashlib.sha256(raw).hexdigest() != row["original"]["sha256"]:
            raise ValueError("original archive checksum mismatch")
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if blob != row["original"]["git_blob"]:
            raise ValueError("original archive Git blob mismatch")
        outputs[name] = raw
    return outputs


def restore(repo, destination):
    repo = repo.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("destination must be a new directory")
    if not destination.parent.is_dir() or any(p.is_symlink() for p in destination.parents):
        raise ValueError("destination parent must be an existing regular directory")
    if destination.is_relative_to(repo):
        raise ValueError("destination must be outside the repository")
    outputs = prepare(repo)
    destination.mkdir(mode=0o700)
    for name, data in outputs.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    print(f"Restored {len(outputs)} available original archives; missing parts remain missing")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    restore(Path(__file__).resolve().parents[3], arguments.destination)
