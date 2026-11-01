#!/usr/bin/env python3
"""Preserve native development evidence as deterministic, byte-exact JSON/gzip archives."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_record(path, relative):
    if path.is_symlink():
        data = str(path.readlink()).encode()
        kind = "symlink"
    else:
        data = path.read_bytes()
        kind = "file"
    return dict(path=relative, kind=kind, bytes=len(data), sha256=sha(data),
                encoding="base64", data=base64.b64encode(data).decode())


def collect(root, prefix):
    return [file_record(p, f"{prefix}/{p.relative_to(root).as_posix()}")
            for p in sorted(root.rglob("*")) if p.is_file() or p.is_symlink()]


def emit(records, name, destination, limit=512000):
    document = dict(schema="digital-read-before-byte-archive-v1", files=records)
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()+b"\n"
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    if len(compressed) >= limit:
        if len(records) < 2:
            raise ValueError(f"single evidence file exceeds archive budget: {records[0]['path']}")
        middle = len(records)//2
        return emit(records[:middle], name+"-a", destination, limit)+emit(records[middle:], name+"-b", destination, limit)
    path = destination/f"{name}.json.gz"
    path.write_bytes(compressed)
    # Verify every archived byte rather than relying only on gzip validity.
    restored = json.loads(gzip.decompress(path.read_bytes()))
    for original, loaded in zip(records, restored["files"], strict=True):
        data = base64.b64decode(loaded["data"], validate=True)
        assert loaded == original and sha(data) == loaded["sha256"] and len(data) == loaded["bytes"]
    return [dict(path=path.name, sha256=sha(compressed), bytes=len(compressed),
                 uncompressed_bytes=len(raw), uncompressed_sha256=sha(raw), files=len(records))]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--development", type=Path, required=True)
    p.add_argument("--qualification", type=Path, required=True)
    p.add_argument("--build", type=Path, required=True)
    p.add_argument("--upstream-receipt", type=Path, required=True)
    p.add_argument("--rust-receipt", type=Path, required=True)
    p.add_argument("--tools-receipt", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    args = p.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    archives = emit(collect(args.development, "development"), "NATIVE_DEVELOPMENT_INPUTS", args.destination)
    archives += emit(collect(args.qualification, "qualification"), "NATIVE_QUALIFICATION_RAW", args.destination)
    build = collect(args.build/"logs", "build/logs")
    for source, name in ((args.build/"build-receipt.json", "build/receipt.json"),
                         (args.build/"codex-rs/Cargo.lock", "build/Cargo.lock"),
                         (args.upstream_receipt, "build/upstream-source-receipt.json"),
                         (args.rust_receipt, "build/rust-official-recovery-receipt.json"),
                         (args.tools_receipt, "build/official-tool-recovery-receipt.json")):
        build.append(file_record(source, name))
    archives += emit(build, "NATIVE_BUILD_LOGS", args.destination)
    manifest = dict(schema="digital-read-before-native-evidence-archives-v1", archives=archives,
                    maximum_archive_bytes=512000, byte_exact=True, gzip_mtime=0,
                    driver_sha256=sha(Path(__file__).read_bytes()),
                    note="Development fit and forced qualification only; no confirmation outcomes.")
    (args.destination/"NATIVE_ARCHIVES.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
