"""Preserve this cost subtree in small gzip-framed parts and verify real restore.

The inherited R12 source, checkpoint and prediction dependencies remain outside
this archive and are identified by each replay INPUT_MANIFEST.json.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def restore(index_path, destination):
    index = json.loads(index_path.read_text())
    base = index_path.parent
    name = index["members_manifest"]
    if Path(name).name != name:
        raise ValueError("Unsafe manifest name")
    metadata = (base / name).read_bytes()
    if digest(metadata) != index["members_manifest_sha256"]:
        raise ValueError("Member manifest changed")
    expected = json.loads(gzip.decompress(metadata))
    segments = []
    for part in index["parts"]:
        if Path(part["name"]).name != part["name"]:
            raise ValueError("Unsafe part name")
        frame = (base / part["name"]).read_bytes()
        if digest(frame) != part["sha256"] or len(frame) != part["bytes"]:
            raise ValueError("Part changed")
        segment = gzip.decompress(frame)
        if digest(segment) != part["segment_sha256"] or len(segment) != part["segment_bytes"]:
            raise ValueError("Part payload changed")
        segments.append(segment)
    rebuilt = b"".join(segments)
    if digest(rebuilt) != index["compressed_archive_sha256"]:
        raise ValueError("Rebuilt archive changed")
    destination.mkdir(parents=True, exist_ok=False)
    observed = {}
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(rebuilt))) as tar:
        for member in tar.getmembers():
            name = Path(member.name)
            if not member.isfile() or name.is_absolute() or ".." in name.parts or "\\" in member.name:
                raise ValueError("Unsafe archive member")
            if member.name not in expected or member.name in observed:
                raise ValueError("Unexpected or repeated archive member")
            data = tar.extractfile(member).read()
            identity = dict(sha256=digest(data), bytes=len(data))
            if identity != expected[member.name]:
                raise ValueError("Archive member differs")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            observed[member.name] = identity
    if observed != expected:
        raise ValueError("Incomplete restored archive")
    return dict(restored_members=len(observed), member_hashes_verified=True)


def package(source, output, file_list=None):
    output.mkdir(parents=True, exist_ok=False)
    if file_list is None:
        files = [p for p in sorted(source.rglob("*")) if p.is_file() and not p.is_symlink()
                 and output not in p.parents and "__pycache__" not in p.parts
                 and "archives" not in p.relative_to(source).parts]
    else:
        names = json.loads(file_list.read_text())
        files = [source / name for name in sorted(set(names))]
        if any(not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(source) for p in files):
            raise ValueError("File selection escapes the source or is not a regular file")
    inventory = {str(p.relative_to(source)): dict(sha256=digest(p.read_bytes()), bytes=p.stat().st_size) for p in files}
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for p in files:
            data = p.read_bytes()
            info = tarfile.TarInfo(str(p.relative_to(source)))
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tar.addfile(info, io.BytesIO(data))
    compressed = gzip.compress(stream.getvalue(), compresslevel=9, mtime=0)
    parts = []
    for index, begin in enumerate(range(0, len(compressed), 400000)):
        segment = compressed[begin:begin + 400000]
        frame = gzip.compress(segment, compresslevel=9, mtime=0)
        name = f"cost-evidence.part{index:04d}.gz"
        (output / name).write_bytes(frame)
        parts.append(dict(name=name, sha256=digest(frame), bytes=len(frame),
                          segment_sha256=digest(segment), segment_bytes=len(segment)))
    members = gzip.compress(json.dumps(inventory, sort_keys=True).encode(), mtime=0)
    (output / "MEMBERS.json.gz").write_bytes(members)
    report = dict(schema="hcsn-r14.cost-evidence-package.v1", member_count=len(files),
        uncompressed_member_bytes=sum(r["bytes"] for r in inventory.values()),
        compressed_archive_bytes=len(compressed), compressed_archive_sha256=digest(compressed),
        members_manifest="MEMBERS.json.gz", members_manifest_sha256=digest(members),
        parts=parts, actual_restore_verified=False,
        files_exceeding_500kib=[dict(path=n, bytes=r["bytes"]) for n, r in inventory.items() if r["bytes"] > 500 * 1024],
        source_sha256=digest(Path(__file__).read_bytes()),
        scope="Explicit selected files stored at repository-relative paths; raw originals are not removed." if file_list else
              "This cost subtree only; inherited R12 dependencies are separately preserved by inputs_01. Raw originals are not removed.",
        selection_manifest_sha256=digest(file_list.read_bytes()) if file_list else None)
    index_path = output / "INDEX.json"
    index_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    with tempfile.TemporaryDirectory(prefix="hcsn-cost-restore-") as temporary:
        restore(index_path, Path(temporary) / "restored")
    report["actual_restore_verified"] = True
    index_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore-index", type=Path)
    parser.add_argument("--file-list", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).parent)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = restore(args.restore_index.resolve(), args.output.resolve()) if args.restore_index else package(args.source.resolve(), args.output.resolve(), args.file_list.resolve() if args.file_list else None)
    print(json.dumps({k: v for k, v in result.items() if k not in ("parts", "files_exceeding_500kib")}, sort_keys=True))
