"""Lossless, bounded evidence packages below the repository's blob-size limit.

Each package records the SHA256 and length of every original file, the complete
deterministic tar.xz archive, and each 400,000-byte transport part. Restoration
verifies all three inventories before writing files. The Git commit supplies
provenance; these unkeyed hashes detect changes, not a hostile author's identity.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


PART_BYTES = 400_000
MAX_RAW_BYTES = 2 * 1024**3
MAX_PARTS = 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or ".." in path.parts or
            str(path) != name or "\\" in name):
        raise ValueError("noncanonical or unsafe archive member")
    return name


def verify_archive(data, files):
    expected = {safe_name(row["path"]): row for row in files}
    if len(expected) != len(files) or sum(row["bytes"] for row in files) > MAX_RAW_BYTES:
        raise ValueError("duplicate members or excessive uncompressed budget")
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
        for member in archive:
            name = safe_name(member.name)
            if not member.isfile() or name not in expected or name in seen:
                raise ValueError("linked, special, duplicate, or unexpected member")
            row = expected[name]
            if member.size != row["bytes"]:
                raise ValueError("member length mismatch")
            stream = archive.extractfile(member)
            if stream is None or hashlib.file_digest(stream, "sha256").hexdigest() != row["sha256"]:
                raise ValueError("member digest mismatch")
            seen.add(name)
    if seen != set(expected):
        raise ValueError("missing archive members")


def load_package(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest["schema"] != "hepta.memory.evidence-parts.v1":
        raise ValueError("unsupported evidence schema")
    if not 1 <= len(manifest["parts"]) <= MAX_PARTS:
        raise ValueError("unbounded part inventory")
    chunks = []
    for index, part in enumerate(manifest["parts"]):
        if part["path"] != f"part-{index:04d}.bin" or not 0 < part["bytes"] <= PART_BYTES:
            raise ValueError("part name, order, or size mismatch")
        path = folder / part["path"]
        if path.is_symlink() or path.stat().st_size != part["bytes"]:
            raise ValueError("linked or incorrectly sized part")
        data = path.read_bytes()
        if sha(data) != part["sha256"]:
            raise ValueError("part digest mismatch")
        chunks.append(data)
    data = b"".join(chunks)
    if len(data) != manifest["archive_bytes"] or sha(data) != manifest["archive_sha256"]:
        raise ValueError("complete archive mismatch")
    verify_archive(data, manifest["files"])
    return manifest, data


def pack(source, output, label):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or source in output.parents:
        raise ValueError("package must be outside its source tree")
    files = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("source tree contains a symbolic link")
        if path.is_file():
            data = path.read_bytes()
            files.append(dict(path=safe_name(path.relative_to(source).as_posix()),
                              bytes=len(data), sha256=sha(data)))
        elif not path.is_dir():
            raise ValueError("source tree contains a special entry")
    if not files or sum(row["bytes"] for row in files) > MAX_RAW_BYTES:
        raise ValueError("empty source or excessive evidence budget")
    output.mkdir(parents=True, exist_ok=False)
    pending = output / "archive.pending"
    with tarfile.open(pending, mode="w:xz", format=tarfile.USTAR_FORMAT, preset=6) as archive:
        for row in files:
            data = (source / row["path"]).read_bytes()
            if len(data) != row["bytes"] or sha(data) != row["sha256"]:
                raise ValueError("source changed during packaging")
            member = tarfile.TarInfo(row["path"])
            member.size, member.mode = len(data), 0o644
            member.mtime = member.uid = member.gid = 0
            archive.addfile(member, io.BytesIO(data))
    data = pending.read_bytes()
    verify_archive(data, files)
    parts = []
    for index, offset in enumerate(range(0, len(data), PART_BYTES)):
        name, chunk = f"part-{index:04d}.bin", data[offset:offset + PART_BYTES]
        with (output / name).open("xb") as stream:
            stream.write(chunk)
        parts.append(dict(path=name, bytes=len(chunk), sha256=sha(chunk)))
    manifest = dict(schema="hepta.memory.evidence-parts.v1", label=label,
                    format="deterministic-ustar+xz", files=files, parts=parts,
                    raw_bytes=sum(row["bytes"] for row in files),
                    archive_bytes=len(data), archive_sha256=sha(data),
                    verification="Every source member and every transport part verified before publication")
    (output / "manifest.json").write_bytes(encoded(manifest))
    load_package(output)
    pending.unlink()
    return manifest


def restore(folder, output):
    manifest, data = load_package(folder)
    output = Path(output)
    # No existing tree can be overwritten, and archives may contain only regular
    # files. Extraction uses our verified names, never tarfile.extractall.
    output.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
        for member in archive:
            target = output / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as destination:
                destination.write(archive.extractfile(member).read())
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    create = subs.add_parser("pack")
    create.add_argument("--source", required=True)
    create.add_argument("--out", required=True)
    create.add_argument("--label", required=True)
    check = subs.add_parser("verify")
    check.add_argument("--pack", required=True)
    unpack = subs.add_parser("restore")
    unpack.add_argument("--pack", required=True)
    unpack.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "pack":
        manifest = pack(args.source, args.out, args.label)
    elif args.command == "restore":
        manifest = restore(args.pack, args.out)
    else:
        manifest, _ = load_package(args.pack)
    print(json.dumps({k: manifest[k] for k in ("label", "raw_bytes", "archive_bytes", "archive_sha256")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
