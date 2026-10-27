"""Losslessly pack measured evidence into hash-bound, repository-sized parts."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile


PART_BYTES = 480000


def identity(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return {"bytes": size, "sha256": digest.hexdigest()}


def safe_relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts):
        raise ValueError("unsafe evidence path")
    return path


def pack(project, output, includes):
    project, output = Path(project).resolve(), Path(output).resolve()
    files = {}
    for relative in includes:
        name = safe_relative(relative)
        root = project.joinpath(*name.parts)
        if not root.exists() or root.is_symlink():
            raise ValueError("missing or linked evidence input")
        for path in sorted(root.rglob("*") if root.is_dir() else [root]):
            if "__pycache__" in path.parts:
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(project):
                raise ValueError("linked evidence input")
            if path.is_file():
                files[path.relative_to(project).as_posix()] = identity(path)
    if not files:
        raise ValueError("empty evidence archive")
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryFile() as compressed:
        with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|") as archive:
                for name, expected in sorted(files.items()):
                    path = project / name
                    info = archive.gettarinfo(str(path), arcname=name)
                    info.mtime, info.uid, info.gid = 0, 0, 0
                    info.uname = info.gname = ""
                    info.mode = 0o644
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
                    if identity(path) != expected:
                        raise ValueError("evidence changed while packing")
        compressed.seek(0)
        parts, digest, size = [], hashlib.sha256(), 0
        while block := compressed.read(PART_BYTES):
            name = f"evidence.tar.gz.part{len(parts) + 1:03d}"
            path = output / name
            path.write_bytes(block)
            parts.append({"path": name, **identity(path)})
            digest.update(block)
            size += len(block)
    manifest = {"schema": "hepta.memory.v5.evidence-archive.v1", "format": "concatenated gzip tar",
                "archive": {"bytes": size, "sha256": digest.hexdigest()}, "parts": parts,
                "files": files, "file_count": len(files), "uncompressed_file_bytes": sum(row["bytes"] for row in files.values())}
    (output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def unpack(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    manifest = json.loads((source / "MANIFEST.json").read_bytes())
    if manifest["schema"] != "hepta.memory.v5.evidence-archive.v1":
        raise ValueError("unknown evidence schema")
    expected = manifest["files"]
    if manifest["file_count"] != len(expected) or manifest["uncompressed_file_bytes"] != sum(row["bytes"] for row in expected.values()):
        raise ValueError("evidence inventory totals differ")
    for name in expected:
        safe_relative(name)
    destination.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryFile() as combined:
        digest, size = hashlib.sha256(), 0
        for index, part in enumerate(manifest["parts"], 1):
            if part["path"] != f"evidence.tar.gz.part{index:03d}":
                raise ValueError("part order or name differs")
            path = source / part["path"]
            if path.is_symlink() or identity(path) != {key: part[key] for key in ("bytes", "sha256")}:
                raise ValueError("corrupt evidence part")
            raw = path.read_bytes()
            combined.write(raw)
            digest.update(raw)
            size += len(raw)
        if {"bytes": size, "sha256": digest.hexdigest()} != manifest["archive"]:
            raise ValueError("archive identity differs")
        combined.seek(0)
        seen = set()
        with tarfile.open(fileobj=combined, mode="r|gz") as archive:
            for member in archive:
                name = str(safe_relative(member.name))
                if not member.isfile() or name in seen or name not in expected or member.size != expected[name]["bytes"]:
                    raise ValueError("unexpected archive member")
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as stream, target.open("xb") as output:
                    while block := stream.read(1024 * 1024):
                        output.write(block)
                if identity(target) != expected[name]:
                    raise ValueError("restored file identity differs")
                seen.add(name)
        if seen != set(expected):
            raise ValueError("missing evidence files")
    return {"files_verified": len(seen), "archive": manifest["archive"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    packing = actions.add_parser("pack")
    packing.add_argument("--project", type=Path, required=True)
    packing.add_argument("--output", type=Path, required=True)
    packing.add_argument("includes", nargs="+")
    unpacking = actions.add_parser("unpack")
    unpacking.add_argument("--source", type=Path, required=True)
    unpacking.add_argument("--destination", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.action == "pack":
        result = pack(arguments.project, arguments.output, arguments.includes)
        print(json.dumps({key: result[key] for key in ("archive", "file_count", "uncompressed_file_bytes")}))
    else:
        print(json.dumps(unpack(arguments.source, arguments.destination)))
