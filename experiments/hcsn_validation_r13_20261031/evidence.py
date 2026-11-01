"""Pack exact repository-relative inputs/results and verify safe reconstruction."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def relative_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or str(path) != name:
        raise ValueError("Expected a normalized repository-relative path")
    return name


def pack(root, paths, output, chunk_bytes=524288):
    """No glob expansion: the explicit file set is part of the input contract."""
    root, output = Path(root).resolve(), Path(output)
    names = sorted(set(relative_name(name) for name in paths))
    if not names or chunk_bytes <= 0:
        raise ValueError("Nonempty input and positive chunk size required")
    output.mkdir(parents=True, exist_ok=False)
    files, chunks = [], []
    with tempfile.TemporaryFile() as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for name in names:
                    path = root / name
                    if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
                        raise ValueError("Only regular files inside the repository are allowed")
                    data = path.read_bytes()
                    member = tarfile.TarInfo(name)
                    member.size, member.mode = len(data), 0o644
                    member.uid = member.gid = member.mtime = 0
                    archive.addfile(member, io.BytesIO(data))
                    files.append(dict(path=name, bytes=len(data), sha256=sha(data)))
        total = stream.tell()
        stream.seek(0)
        combined = hashlib.sha256()
        while data := stream.read(chunk_bytes):
            name = f"evidence.tar.gz.part{len(chunks):04d}"
            (output / name).write_bytes(data)
            combined.update(data)
            chunks.append(dict(path=name, bytes=len(data), sha256=sha(data)))
    index = dict(schema="hcsn.r13.evidence.v1", files=files, chunks=chunks,
                 compressed_bytes=total, compressed_sha256=combined.hexdigest(),
                 format="Concatenate ordered parts and decompress gzip tar; restore paths are repository-relative")
    (output / "INDEX.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    return index


def restore(index_path, destination):
    """Hash every member; never overwrite different content or follow symlinks."""
    index_path, destination = Path(index_path), Path(destination).resolve()
    record = json.loads(index_path.read_text())
    if record["schema"] != "hcsn.r13.evidence.v1":
        raise ValueError("Unsupported archive schema")
    expected = {relative_name(row["path"]): row for row in record["files"]}
    if len(expected) != len(record["files"]):
        raise ValueError("Duplicate input member")
    seen = set()
    with tempfile.TemporaryFile() as stream:
        combined = hashlib.sha256()
        for row in record["chunks"]:
            name = relative_name(row["path"])
            if "/" in name:
                raise ValueError("Archive parts must be adjacent to INDEX")
            data = (index_path.parent / name).read_bytes()
            if len(data) != row["bytes"] or sha(data) != row["sha256"]:
                raise ValueError("Archive part identity mismatch")
            stream.write(data)
            combined.update(data)
        if stream.tell() != record["compressed_bytes"] or combined.hexdigest() != record["compressed_sha256"]:
            raise ValueError("Combined archive identity mismatch")
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:gz") as archive:
            for member in archive:
                if not member.isfile() or member.name not in expected or member.name in seen:
                    raise ValueError("Unexpected, duplicate, or non-file archive member")
                row = expected[member.name]
                if member.size != row["bytes"]:
                    raise ValueError("Member length mismatch")
                data = archive.extractfile(member).read()
                if sha(data) != row["sha256"]:
                    raise ValueError("Member content identity mismatch")
                path = destination / member.name
                if path.is_symlink() or destination not in path.resolve().parents:
                    raise ValueError("Unsafe destination")
                if path.exists():
                    if not path.is_file() or path.read_bytes() != data:
                        raise FileExistsError("Refusing to replace existing different content: " + member.name)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as target:
                        target.write(data)
                seen.add(member.name)
    if seen != set(expected):
        raise ValueError("Archive lacks a declared member")
    return dict(verified_files=len(seen), verified_bytes=sum(r["bytes"] for r in expected.values()),
                destination=str(destination))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    creation = actions.add_parser("pack")
    creation.add_argument("--root", type=Path, required=True)
    creation.add_argument("--paths", type=Path, required=True, help="JSON array of repository-relative paths")
    creation.add_argument("--output", type=Path, required=True)
    creation.add_argument("--chunk-bytes", type=int, default=524288)
    extraction = actions.add_parser("restore")
    extraction.add_argument("--index", type=Path, required=True)
    extraction.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "pack":
        result = pack(args.root, json.loads(args.paths.read_text()), args.output, args.chunk_bytes)
        result = {key: value for key, value in result.items() if key not in ("files", "chunks")}
    else:
        result = restore(args.index, args.destination)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
