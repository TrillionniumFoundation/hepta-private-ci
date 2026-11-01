"""Pack immutable raw evidence into bounded Git assets; verify every byte.

Only raw gzip files are packed. Reports, receipts, source and model manifests
remain directly readable. The original local files are retained unchanged.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PART_BYTES = 480000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pack(source, bundle):
    source, bundle = Path(source).resolve(), Path(bundle).resolve()
    if not source.is_relative_to(ROOT) or not bundle.is_relative_to(ROOT):
        raise ValueError("Evidence paths must be inside this repository")
    files = sorted(source.rglob("raw_*.json.gz"))
    if not files:
        # The finite control campaign uses fit/domain names for its raw files.
        files = sorted(source.glob("*.json.gz"))
    if not files:
        raise ValueError("No raw evidence files")
    records, tar_buffer = [], io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
        for path in files:
            data = path.read_bytes()
            relative = path.relative_to(ROOT).as_posix()
            info = tarfile.TarInfo(relative)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            archive.addfile(info, io.BytesIO(data))
            records.append(dict(path=relative, bytes=len(data), sha256=sha(data),
                                git_blob_sha1=hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()))
    compressed = gzip.compress(tar_buffer.getvalue(), mtime=0)
    # Independent container readback verifies every archived original byte.
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(compressed)), mode="r:") as archive:
        members = archive.getmembers()
        if [member.name for member in members] != [row["path"] for row in records]:
            raise RuntimeError("Archive path inventory mismatch")
        for member, row in zip(members, records, strict=True):
            data = archive.extractfile(member).read()
            if sha(data) != row["sha256"] or len(data) != row["bytes"]:
                raise RuntimeError("Archive bytes differ from raw evidence")
    bundle.mkdir(parents=True, exist_ok=False)
    parts = []
    for index, begin in enumerate(range(0, len(compressed), PART_BYTES)):
        data = compressed[begin:begin + PART_BYTES]
        path = bundle / f"EVIDENCE.part-{index:03d}.bin"
        path.write_bytes(data)
        parts.append(dict(path=path.name, bytes=len(data), sha256=sha(data)))
    record = dict(schema="hcsn-r16-raw-archive-v1", source_root=source.relative_to(ROOT).as_posix(),
                  archive_format="Concatenate parts, gzip-decompress, then read POSIX tar",
                  archive_bytes=len(compressed), archive_sha256=sha(compressed),
                  parts=parts, files=records, local_byte_readback_verified=True,
                  originals_retained_locally=True,
                  raw_hashes_unchanged=True)
    (bundle / "INDEX.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(source=record["source_root"], files=len(files), parts=len(parts),
                          bytes=len(compressed), verified=True)))


def restore(bundle, destination):
    bundle, destination = Path(bundle).resolve(), Path(destination).resolve()
    manifest = json.loads((bundle / "INDEX.json").read_text())
    chunks = []
    for part in manifest["parts"]:
        if Path(part["path"]).name != part["path"]:
            raise ValueError("Invalid part name")
        data = (bundle / part["path"]).read_bytes()
        if len(data) != part["bytes"] or sha(data) != part["sha256"]:
            raise ValueError("Evidence part hash/size mismatch")
        chunks.append(data)
    compressed = b"".join(chunks)
    if sha(compressed) != manifest["archive_sha256"] or len(compressed) != manifest["archive_bytes"]:
        raise ValueError("Combined archive mismatch")
    expected = {row["path"]: row for row in manifest["files"]}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(compressed)), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile() or member.name not in expected or member.name in seen:
                raise ValueError("Unexpected archive member")
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination):
                raise ValueError("Archive path escapes destination")
            data = archive.extractfile(member).read()
            row = expected[member.name]
            if len(data) != row["bytes"] or sha(data) != row["sha256"]:
                raise ValueError("Archived file mismatch")
            if target.exists() and target.read_bytes() != data:
                raise ValueError("Refusing to overwrite different local evidence")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            seen.add(member.name)
    if seen != set(expected):
        raise ValueError("Missing archive member")
    print(json.dumps(dict(restored=len(seen), verified=True)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("pack", "restore"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.operation == "pack":
        pack(args.source, args.bundle)
    else:
        restore(args.bundle, args.destination)
