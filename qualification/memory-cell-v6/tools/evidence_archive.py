"""Package or recover all retained evidence with bounded, verified transport parts."""

import argparse
import hashlib
import json
import lzma
from pathlib import Path
import shutil
import tarfile
import tempfile


def identity(path):
    checksum, length = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
            length += len(block)
    return {"bytes": length, "sha256": checksum.hexdigest()}


def pack(specification, index):
    specification, index = Path(specification), Path(index)
    roots = json.loads(specification.read_bytes())
    if index.exists():
        raise ValueError("evidence index already exists")
    index.parent.mkdir(parents=True, exist_ok=True)
    files, inventory = [], {}
    for name, source in sorted(roots.items()):
        source = Path(source)
        if Path(name).is_absolute() or ".." in Path(name).parts or source.is_symlink():
            raise ValueError("invalid archive root")
        paths = [source] if source.is_file() else sorted(source.rglob("*"))
        if any(path.is_symlink() for path in paths):
            raise ValueError("symlinked evidence")
        for path in paths:
            if not path.is_file():
                continue
            relative = (
                name if source.is_file() else str(Path(name) / path.relative_to(source))
            )
            if relative in inventory:
                raise ValueError("duplicate evidence path")
            inventory[relative] = identity(path)
            files.append((relative, path))
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / "v6-evidence.tar.xz"
        filters = [
            {"id": lzma.FILTER_LZMA2, "preset": 6, "dict_size": 64 * 1024 * 1024}
        ]
        with (
            lzma.open(archive, "wb", filters=filters) as compressed,
            tarfile.open(fileobj=compressed, mode="w|") as output,
        ):
            for name, path in files:
                info = output.gettarinfo(path, arcname=name)
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with path.open("rb") as payload:
                    output.addfile(info, payload)
        archive_identity, parts = identity(archive), []
        with archive.open("rb") as stream:
            number = 0
            while block := stream.read(500_000):
                name = f"v6-evidence.tar.xz.part{number:03}"
                path = index.parent / name
                with path.open("xb") as output:
                    output.write(block)
                parts.append({"path": name, **identity(path)})
                number += 1
    result = {
        "schema": "hepta.memory.v6.evidence-archive.v1",
        "archive": archive_identity,
        "parts": parts,
        "files": inventory,
        "file_count": len(inventory),
        "uncompressed_file_bytes": sum(item["bytes"] for item in inventory.values()),
        "format": "concatenated ordered parts, then standard tar.xz",
        "scope": "Retained formal and development records; pinned public encoder weights are downloaded separately. Historical temporary development artifacts explicitly marked missing remain unavailable.",
    }
    index.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("archive", "file_count", "uncompressed_file_bytes")
            }
        )
    )


def unpack(index, output):
    index, output = Path(index), Path(output).absolute()
    manifest = json.loads(index.read_bytes())
    if manifest["schema"] != "hepta.memory.v6.evidence-archive.v1" or output.exists():
        raise ValueError("invalid archive schema or output already exists")
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        archive = Path(temporary) / "evidence.tar.xz"
        with archive.open("xb") as assembled:
            for part in manifest["parts"]:
                if Path(part["path"]).name != part["path"]:
                    raise ValueError("invalid transport part path")
                path = index.parent / part["path"]
                if path.is_symlink() or identity(path) != {
                    key: part[key] for key in ("bytes", "sha256")
                }:
                    raise ValueError("transport part integrity failure")
                with path.open("rb") as source:
                    shutil.copyfileobj(source, assembled)
        if identity(archive) != manifest["archive"]:
            raise ValueError("complete archive integrity failure")
        observed = set()
        with tarfile.open(archive, "r|xz") as source:
            for member in source:
                name = Path(member.name)
                if (
                    not member.isfile()
                    or name.is_absolute()
                    or ".." in name.parts
                    or member.name not in manifest["files"]
                    or member.name in observed
                ):
                    raise ValueError("unexpected or unsafe archive member")
                if member.size != manifest["files"][member.name]["bytes"]:
                    raise ValueError("archive member length differs")
                path = output / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as payload, path.open("xb") as target:
                    shutil.copyfileobj(payload, target)
                if identity(path) != manifest["files"][member.name]:
                    raise ValueError("extracted file identity differs")
                observed.add(member.name)
        if observed != set(manifest["files"]):
            raise ValueError("archive omitted evidence")
    print(
        json.dumps(
            {
                "verified_files": len(observed),
                "archive_sha256": manifest["archive"]["sha256"],
                "output": str(output),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    packing = subparsers.add_parser("pack")
    packing.add_argument("--specification", required=True, type=Path)
    packing.add_argument("--index", required=True, type=Path)
    extracting = subparsers.add_parser("unpack")
    extracting.add_argument("--index", required=True, type=Path)
    extracting.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.command == "pack":
        pack(arguments.specification, arguments.index)
    else:
        unpack(arguments.index, arguments.output)
