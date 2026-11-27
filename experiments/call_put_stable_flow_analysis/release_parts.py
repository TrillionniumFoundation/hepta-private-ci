"""Split, verify, and reconstruct the public evidence archive without dependencies.

Parts avoid transport-size limits. Every part and the combined byte stream
are checked; reconstructing an archive never reruns an experiment.
"""

import argparse
import hashlib
import json
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def filename(value):
    require(
        isinstance(value, str)
        and bool(value)
        and value not in (".", "..")
        and Path(value).name == value
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value,
        "Part names must be plain filenames",
    )
    return value


def load_manifest(path):
    require(path.is_file() and not path.is_symlink(), "Manifest must be a regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(
        value["schema"] == "hepta-archive-parts-v1" and value["parts"],
        "Unknown or empty part manifest",
    )
    require(
        [row["index"] for row in value["parts"]] == list(range(len(value["parts"]))),
        "Part order is incomplete or duplicated",
    )
    names = [filename(row["filename"]) for row in value["parts"]]
    require(len(set(names)) == len(names), "Duplicate part filename")
    require(
        all(
            isinstance(row["bytes"], int) and row["bytes"] > 0 for row in value["parts"]
        ),
        "Part byte lengths must be positive",
    )
    require(
        sum(row["bytes"] for row in value["parts"]) == value["archive"]["bytes"],
        "Part lengths do not reconstruct the archive length",
    )
    return value


def verify(path):
    value = load_manifest(path)
    total, combined = 0, hashlib.sha256()
    for row in value["parts"]:
        part = path.parent / row["filename"]
        require(part.is_file() and not part.is_symlink(), "Part missing or symlinked")
        require(part.stat().st_size == row["bytes"], "Part byte length changed")
        own = hashlib.sha256()
        with part.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                own.update(block)
                combined.update(block)
                total += len(block)
        require(own.hexdigest() == row["sha256"], "Part SHA256 mismatch")
    require(
        total == value["archive"]["bytes"]
        and combined.hexdigest() == value["archive"]["sha256"],
        "Combined archive identity mismatch",
    )
    return {
        "status": "all_parts_and_combined_archive_verified",
        "parts": len(value["parts"]),
        "bytes": total,
        "sha256": combined.hexdigest(),
        "manifest_sha256": sha(path),
    }


def split(archive, output, part_bytes):
    require(part_bytes > 0, "Part byte budget must be positive")
    require(
        archive.is_file() and archive.stat().st_size > 0 and not archive.is_symlink(),
        "Archive must be nonempty and regular",
    )
    output.mkdir(parents=True, exist_ok=False)
    initial_sha, initial_size = sha(archive), archive.stat().st_size
    rows = []
    with archive.open("rb") as stream:
        index = 0
        while block := stream.read(part_bytes):
            name = archive.name + f".part-{index:03d}"
            with (output / name).open("xb") as destination:
                destination.write(block)
            rows.append(
                {
                    "index": index,
                    "filename": name,
                    "bytes": len(block),
                    "sha256": hashlib.sha256(block).hexdigest(),
                }
            )
            index += 1
    require(
        sha(archive) == initial_sha and archive.stat().st_size == initial_size,
        "Archive changed while splitting; do not publish these parts",
    )
    manifest = {
        "schema": "hepta-archive-parts-v1",
        "part_bytes": part_bytes,
        "archive": {
            "filename": filename(archive.name),
            "bytes": initial_size,
            "sha256": initial_sha,
        },
        "parts": rows,
        "meaning": "Complete exact archive bytes split only for transport; no scientific regeneration",
    }
    path = output / "PARTS.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return verify(path)


def assemble(manifest_path, output):
    expected = verify(manifest_path)
    value = load_manifest(manifest_path)
    require(not output.exists(), "Refuse to overwrite an archive")
    output.parent.mkdir(parents=True, exist_ok=True)
    combined, total = hashlib.sha256(), 0
    with output.open("xb") as destination:
        for row in value["parts"]:
            part = manifest_path.parent / row["filename"]
            require(
                part.is_file() and not part.is_symlink(),
                "Part changed before reconstruction",
            )
            own, count = hashlib.sha256(), 0
            with part.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    destination.write(block)
                    combined.update(block)
                    own.update(block)
                    count += len(block)
                    total += len(block)
            require(
                own.hexdigest() == row["sha256"] and count == row["bytes"],
                "Part changed during reconstruction",
            )
    require(
        total == expected["bytes"] and combined.hexdigest() == expected["sha256"],
        "Reconstructed archive identity mismatch",
    )
    return {
        "status": "archive_reconstructed_exactly",
        "bytes": total,
        "sha256": combined.hexdigest(),
        "output": str(output),
        "next_check": "release.py verify --archive OUTPUT",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    partition = commands.add_parser("split")
    partition.add_argument("--archive", type=Path, required=True)
    partition.add_argument("--output", type=Path, required=True)
    partition.add_argument("--part-bytes", type=int, default=2 * 1024 * 1024)
    check = commands.add_parser("verify")
    check.add_argument("--manifest", type=Path, required=True)
    restore = commands.add_parser("assemble")
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "split":
        result = split(args.archive, args.output, args.part_bytes)
    elif args.command == "verify":
        result = verify(args.manifest)
    else:
        result = assemble(args.manifest, args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
