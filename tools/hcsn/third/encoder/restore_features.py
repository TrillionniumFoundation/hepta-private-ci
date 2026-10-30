"""Restore the exact audited feature caches using only Python's standard library.

This is an appended delivery mechanism, not a new experiment or a change to
the frozen sample selection. No raw examples, encoder weights or network
access are required. Each complete cache is verified before atomic replace.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


HERE = Path(__file__).resolve().parent
PARTS = HERE / "features"
DEFAULT_OUTPUT = Path("/tmp/hcsn-third-encoder-assets")


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def basename(value):
    if not isinstance(value, str) or not value or value in (".", ".."):
        raise ValueError("Expected a nonempty file name")
    if Path(value).name != value or "/" in value or "\\" in value:
        raise ValueError("Manifest file names must not contain paths")
    return value


def restore(record, output):
    filename = basename(record["filename"])
    target = output / filename
    expected_size, expected_hash = record["size_bytes"], record["sha256"]
    if sum(part["size_bytes"] for part in record["parts"]) != expected_size:
        raise ValueError("Part sizes do not sum to the declared complete cache")
    if target.is_file() and target.stat().st_size == expected_size and digest(target) == expected_hash:
        return dict(dataset=record["dataset"], path=str(target), sha256=expected_hash,
                    size_bytes=expected_size, status="existing_exact_cache_verified")

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=filename+".", suffix=".partial",
                                         dir=output, delete=False) as handle:
            temporary = Path(handle.name)
            complete = hashlib.sha256()
            written = 0
            for number, part in enumerate(record["parts"]):
                if part["index"] != number:
                    raise ValueError("Part sequence is incomplete or out of order")
                name = basename(part["name"])
                source = (PARTS / name).resolve()
                if not source.is_relative_to(PARTS.resolve()):
                    raise ValueError("Part path escapes the delivery directory")
                block = source.read_bytes()
                if len(block) != part["size_bytes"] or hashlib.sha256(block).hexdigest() != part["sha256"]:
                    raise ValueError("Part integrity failure: "+name)
                git_hash = hashlib.sha1(b"blob "+str(len(block)).encode()+b"\0"+block).hexdigest()
                if git_hash != part["git_blob_sha"]:
                    raise ValueError("Git blob identity mismatch: "+name)
                handle.write(block)
                complete.update(block)
                written += len(block)
            handle.flush()
            os.fsync(handle.fileno())
        if written != expected_size or complete.hexdigest() != expected_hash:
            raise ValueError("Reconstructed cache does not match the audited full-file SHA256")
        # Verify the materialized file, not only the bytes supplied to write().
        if temporary.stat().st_size != expected_size or digest(temporary) != expected_hash:
            raise ValueError("Materialized cache failed the final integrity check")
        os.replace(temporary, target)
        temporary = None
        return dict(dataset=record["dataset"], path=str(target), sha256=expected_hash,
                    size_bytes=written, parts=len(record["parts"]), status="restored_and_verified")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dataset", choices=("all", "ag_news", "cifar10"), default="all")
    args = parser.parse_args()
    manifest = json.loads((PARTS / "manifest.json").read_text())
    if manifest["schema"] != "hepta.hcsn.encoder.feature_parts.v1":
        raise ValueError("Unsupported feature delivery schema")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for record in manifest["datasets"]:
        if args.dataset in ("all", record["dataset"]):
            print(json.dumps(restore(record, output), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
