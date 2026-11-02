"""Preserve original NPZ bytes in deterministic tar slices for Git transport.

The gzip layers wrap tar slices; no NPZ member is decoded or rewritten.
This operates on a controlled local filesystem, not hostile concurrent writers.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile

SCHEMA = "hcsn-v10-original-npz-transport.v1"
RAW_LIMIT = 850000
PART_LIMIT = 900000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def relative(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\0" in name:
        raise ValueError("Invalid relative path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(x in ("", ".", "..") for x in name.split("/")):
        raise ValueError("Unsafe relative path")
    return path


def root_path(value):
    path = Path(os.path.abspath(value))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink root refused")
    if path.exists() and not path.is_dir():
        raise ValueError("Root is not a directory")
    return path


def checked(root, name):
    path = root
    for piece in relative(name).parts:
        path = path / piece
        if path.is_symlink():
            raise ValueError("Symlink refused")
    return path


def direct_copy(path):
    return path.name == "selected.npz" or (
        path.name.startswith("selected-prefix") and path.name.endswith("-test.npz"))


def pack(root, scope, output):
    root, output = root_path(root), root_path(output)
    scoped = checked(root, scope)
    if not scoped.is_dir() or not output.is_relative_to(root):
        raise ValueError("Missing scope or output outside repository")
    if (output / "MANIFEST.json").exists():
        raise FileExistsError("Manifest already exists")
    originals = []
    for path in sorted(scoped.rglob("*")):
        if path.is_symlink():
            raise ValueError("Source symlink refused")
        if path.is_file() and path.suffix == ".npz":
            originals.append(path)
    if not originals:
        raise ValueError("No NPZ originals found")
    output.mkdir(parents=True, exist_ok=True)
    (output / "parts").mkdir(exist_ok=True)
    files, parts = [], []
    with tempfile.TemporaryFile() as archive:
        with tarfile.open(fileobj=archive, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            for path in originals:
                name = path.relative_to(root).as_posix()
                data = checked(root, name).read_bytes()
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                tar.addfile(info, io.BytesIO(data))
                files.append({"path": name, "bytes": len(data), "sha256": sha(data),
                              "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
                              "direct_copy": direct_copy(path)})
        archive.seek(0)
        full, total = hashlib.sha256(), 0
        while raw := archive.read(RAW_LIMIT):
            wrapped = io.BytesIO()
            with gzip.GzipFile(fileobj=wrapped, mode="wb", filename="", mtime=0, compresslevel=6) as stream:
                stream.write(raw)
            data = wrapped.getvalue()
            if len(data) > PART_LIMIT:
                raise ValueError("Transport part exceeds bound")
            name = f"parts/{len(parts):04d}.gz"
            with checked(output, name).open("xb") as stream:
                stream.write(data)
            parts.append({"path": name, "bytes": len(data), "sha256": sha(data),
                          "raw_bytes": len(raw), "raw_sha256": sha(raw)})
            full.update(raw)
            total += len(raw)
        for item in files:
            if sha(checked(root, item["path"]).read_bytes()) != item["sha256"]:
                raise ValueError("Original changed during packing")
    manifest = {"schema": SCHEMA, "scope": str(relative(scope)), "files": files, "parts": parts,
                "file_count": len(files), "original_total_bytes": sum(x["bytes"] for x in files),
                "tar_bytes": total, "tar_sha256": full.hexdigest(), "raw_slice_limit": RAW_LIMIT,
                "published_part_limit": PART_LIMIT, "gzip_mtime": 0,
                "originals_decoded_or_rewritten": False,
                "format": "Concatenate gzip-decoded tar slices; extract each original member without rewriting its bytes",
                "direct_copies": [x["path"] for x in files if x["direct_copy"]]}
    with (output / "MANIFEST.json").open("x") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    return {"files": len(files), "parts": len(parts), "original_bytes": manifest["original_total_bytes"],
            "published_part_bytes": sum(x["bytes"] for x in parts),
            "maximum_part_bytes": max(x["bytes"] for x in parts), "direct_copies": len(manifest["direct_copies"])}


def load_manifest(path):
    path = Path(os.path.abspath(path))
    base = root_path(path.parent)
    if path.is_symlink() or path.stat().st_size > 10000000:
        raise ValueError("Invalid manifest")
    value = json.loads(path.read_text())
    if value.get("schema") != SCHEMA or value.get("raw_slice_limit") != RAW_LIMIT:
        raise ValueError("Unsupported format")
    if not isinstance(value.get("files"), list) or not 1 <= len(value["files"]) <= 10000:
        raise ValueError("Invalid file count")
    if not isinstance(value.get("parts"), list) or not 1 <= len(value["parts"]) <= 256:
        raise ValueError("Invalid part count")
    scope, seen = relative(value["scope"]), set()
    for row in value["files"]:
        name = relative(row["path"])
        if not name.is_relative_to(scope) or row["path"] in seen or type(row["bytes"]) is not int or row["bytes"] < 1:
            raise ValueError("Invalid original inventory")
        seen.add(row["path"])
    if value["file_count"] != len(seen) or value["original_total_bytes"] != sum(x["bytes"] for x in value["files"]):
        raise ValueError("Manifest totals disagree")
    names = set()
    for row in value["parts"]:
        name = str(relative(row["path"]))
        if not name.startswith("parts/") or name in names:
            raise ValueError("Invalid part path")
        names.add(name)
        if type(row["bytes"]) is not int or not 1 <= row["bytes"] <= PART_LIMIT:
            raise ValueError("Invalid wrapped length")
        if type(row["raw_bytes"]) is not int or not 1 <= row["raw_bytes"] <= RAW_LIMIT:
            raise ValueError("Invalid raw length")
        data = checked(base, name).read_bytes()
        if len(data) != row["bytes"] or sha(data) != row["sha256"]:
            raise ValueError("Transport part identity mismatch")
    if value["tar_bytes"] != sum(x["raw_bytes"] for x in value["parts"]):
        raise ValueError("Tar length disagrees with parts")
    return base, value


def restore(manifest_path, destination):
    base, value = load_manifest(manifest_path)
    destination = root_path(destination)
    expected = {x["path"]: x for x in value["files"]}
    with tempfile.TemporaryFile() as archive:
        full, total = hashlib.sha256(), 0
        for row in value["parts"]:
            with gzip.open(checked(base, row["path"]), "rb") as stream:
                raw = stream.read(RAW_LIMIT + 1)
            if len(raw) != row["raw_bytes"] or sha(raw) != row["raw_sha256"]:
                raise ValueError("Decoded part identity mismatch")
            archive.write(raw)
            full.update(raw)
            total += len(raw)
        if total != value["tar_bytes"] or full.hexdigest() != value["tar_sha256"]:
            raise ValueError("Combined tar identity mismatch")
        archive.seek(0)
        with tarfile.open(fileobj=archive, mode="r:") as tar:
            seen = set()
            for item in tar:
                row = expected.get(item.name)
                if row is None or item.name in seen or not item.isfile() or item.size != row["bytes"]:
                    raise ValueError("Tar inventory differs from original inventory")
                checked(destination, item.name)
                if sha(tar.extractfile(item).read()) != row["sha256"]:
                    raise ValueError("Original member digest mismatch")
                seen.add(item.name)
            if seen != set(expected):
                raise ValueError("Missing tar member")
            # Verify all archives and existing destinations before installing any member.
            for name, row in expected.items():
                target = checked(destination, name)
                if target.exists() and (not target.is_file() or sha(target.read_bytes()) != row["sha256"]):
                    raise FileExistsError("Conflicting existing original: " + name)
                if any(p.exists() and not p.is_dir() for p in target.parents):
                    raise FileExistsError("Destination ancestor is not a directory")
            installed = reused = 0
            for name, row in expected.items():
                target = checked(destination, name)
                if target.exists():
                    reused += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary_name = tempfile.mkstemp(prefix=".transport-", dir=target.parent)
                temporary = Path(temporary_name)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(tar.extractfile(name).read())
                    if temporary.stat().st_size != row["bytes"] or sha(temporary.read_bytes()) != row["sha256"]:
                        raise ValueError("Temporary original changed")
                    checked(destination, name)
                    os.link(temporary, target)
                    installed += 1
                finally:
                    temporary.unlink(missing_ok=True)
    return {"schema": SCHEMA, "installed_files": installed, "identical_existing_files": reused,
            "verified_original_bytes": value["original_total_bytes"], "all_original_bytes_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    packing = sub.add_parser("pack")
    packing.add_argument("--root", type=Path, required=True)
    packing.add_argument("--scope", required=True)
    packing.add_argument("--output", type=Path, required=True)
    restoring = sub.add_parser("restore")
    restoring.add_argument("--manifest", type=Path, required=True)
    restoring.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    value = (pack(args.root, args.scope, args.output) if args.command == "pack"
             else restore(args.manifest, args.destination))
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()
