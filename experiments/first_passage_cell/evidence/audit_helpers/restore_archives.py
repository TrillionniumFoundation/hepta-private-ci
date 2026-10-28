"""Restore exact frozen synthetic evidence from bounded Git blob parts.

No data are regenerated, no pickle is loaded, and no existing differing file
is overwritten. Chunking only accommodates the evidence transfer interface.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2]
REPOSITORY = PACKAGE.parents[1]
PART_ROOT = "experiments/first_passage_cell/evidence/data_parts/"
OUTPUT_ROOTS = ("experiments/first_passage_cell/prepared/",
                "experiments/first_passage_cell/runs/",
                "experiments/first_passage_cell/evidence/aborted_policy_preparation_01/")


def safe_path(name, prefixes):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not any(name.startswith(p) for p in prefixes):
        raise ValueError("Archive path is outside the package-owned evidence directories")
    return REPOSITORY / path


def identities(path):
    path = Path(path)
    size = path.stat().st_size
    sha256 = hashlib.sha256()
    git = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha256.update(block)
            git.update(block)
    return size, sha256.hexdigest(), git.hexdigest()


def expected(record):
    return record["bytes"], record["sha256"], record["git_blob_sha"]


def restore_record(record, verify_only=False):
    destination = safe_path(record["path"], OUTPUT_ROOTS)
    parts = record.get("parts", [])
    for part in parts:
        path = safe_path(part["path"], (PART_ROOT,))
        if identities(path) != expected(part):
            raise ValueError("Corrupt or missing stored part: " + part["path"])
    if destination.exists():
        if identities(destination) != expected(record):
            raise ValueError("Refusing to overwrite a differing evidence file: " + record["path"])
        return "already_exact"
    if not parts:
        raise ValueError("Missing directly tracked evidence file: " + record["path"])
    if verify_only:
        raise ValueError("Frozen evidence has not been restored: " + record["path"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".restore-incomplete")
    try:
        with temporary.open("xb") as output:
            for part in parts:
                with safe_path(part["path"], (PART_ROOT,)).open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        output.write(block)
        if identities(temporary) != expected(record):
            raise ValueError("Reassembled evidence identity does not match the frozen original")
        # Link is exclusive, so another writer cannot be silently overwritten.
        os.link(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "restored_exact"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PACKAGE / "EVIDENCE_ARCHIVE.json")
    parser.add_argument("--only", help="An exact repository-relative original artifact path")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if manifest.get("schema") != "HeptaFirstPassageEvidenceArchiveV1":
        raise ValueError("Unknown evidence archive schema")
    records = manifest["files"]
    names = [row["path"] for row in records]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate original artifact path")
    if args.only:
        records = [row for row in records if row["path"] == args.only]
        if not records:
            raise ValueError("Requested artifact is not in the frozen archive")
    counts = {"already_exact": 0, "restored_exact": 0}
    for record in records:
        counts[restore_record(record, args.verify_only)] += 1
    print(json.dumps({"schema": "HeptaFirstPassageArchiveRestoreV1", "pass": True,
                      "files": len(records), **counts}, sort_keys=True))


if __name__ == "__main__":
    main()
