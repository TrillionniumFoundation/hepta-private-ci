"""Restore byte-identical historical evidence into a new external directory."""

import argparse
import hashlib
import json
from pathlib import Path

from restore_raw_evidence import read_verified


MANIFESTS = (
    "qualification/evaluated-current-read-20261112/source53-native-failure/"
    "METHOD_RESULTS.jsonl.parts.json",
    "qualification/neuroscience-20261110/PUBLICATION_MANIFEST.json.parts.json",
)


def prepare(repo, manifest_name):
    manifest_path = repo / manifest_name
    manifest = json.loads(manifest_path.read_text())
    relative = Path(manifest["original_repository_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("original path must remain relative to the repository")
    data = bytearray()
    for part in manifest["ordered_parts"]:
        name = Path(part["path"])
        if name.name != str(name) or name.is_absolute():
            raise ValueError("part must be a filename beside its manifest")
        path = manifest_path.parent / name
        chunk = read_verified(
            repo, path.relative_to(repo), part["bytes"], part["sha256"]
        )
        if part["offset"] != len(data) or part["bytes"] != len(chunk):
            raise ValueError(f"part length or offset mismatch: {path}")
        if hashlib.sha256(chunk).hexdigest() != part["sha256"]:
            raise ValueError(f"part checksum mismatch: {path}")
        data.extend(chunk)
    if len(data) != manifest["archive_bytes"]:
        raise ValueError(f"original length mismatch: {manifest_path}")
    if hashlib.sha256(data).hexdigest() != manifest["archive_sha256"]:
        raise ValueError(f"original checksum mismatch: {manifest_path}")
    return relative, bytes(data)


def restore(repo, destination):
    repo = repo.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("destination must be a new directory")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError("destination parent must be an existing regular directory")
    outputs = [prepare(repo, name) for name in MANIFESTS]
    destination.mkdir(mode=0o700)
    for relative, data in outputs:
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(data)
        print(f"Restored {relative}: {len(data)} bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    restore(Path(__file__).resolve().parents[3], arguments.destination)
