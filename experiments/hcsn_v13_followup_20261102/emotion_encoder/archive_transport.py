"""Preserve the exact downloaded CI ZIP in bounded public Git blobs."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def restore(directory, destination):
    manifest = json.loads((directory / "ARCHIVE_TRANSPORT.json").read_text())
    seen, size = set(), 0
    with destination.open("xb") as output:
        for item in manifest["parts"]:
            name = item["name"]
            if Path(name).name != name or name in seen:
                raise ValueError("Unsafe or duplicate raw ZIP part")
            seen.add(name)
            path = directory / name
            if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
                raise ValueError("Raw ZIP part differs")
            output.write(path.read_bytes()); size += item["bytes"]
    if size != manifest["bytes"] or sha(destination) != manifest["sha256"]:
        raise ValueError("Reassembled original CI ZIP differs")


def pack(archive, directory):
    directory.mkdir(parents=True, exist_ok=False)
    parts = []
    with archive.open("rb") as stream:
        while block := stream.read(4_500_000):
            name = f"original-ci-zip.part{len(parts):03d}"
            path = directory / name
            path.write_bytes(block)
            parts.append({"name": name, "bytes": len(block), "sha256": sha(path)})
    manifest = {"schema": "hcsn-v13-exact-original-ci-zip-transport.v1", "filename": archive.name,
                "bytes": archive.stat().st_size, "sha256": sha(archive), "parts": parts}
    (directory / "ARCHIVE_TRANSPORT.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with tempfile.TemporaryDirectory(prefix="v13-zip-roundtrip-") as scratch:
        restore(directory, Path(scratch) / archive.name)
    (directory / "ROUNDTRIP.json").write_text(json.dumps({"whole_sha256": manifest["sha256"],
        "reassembled_byte_identity_passed": True, "parts": len(parts), "original_archive_unchanged": True}, indent=2) + "\n")
    print(json.dumps({"parts": len(parts), "bytes": manifest["bytes"], "sha256": manifest["sha256"], "roundtrip": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("pack", "restore"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    pack(args.archive, args.directory) if args.mode == "pack" else restore(args.directory, args.archive)
