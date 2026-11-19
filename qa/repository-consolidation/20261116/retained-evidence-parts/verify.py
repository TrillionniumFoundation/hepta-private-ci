#!/usr/bin/env python3
"""Verify retained evidence parts and optionally restore their original bytes."""

import argparse
import json
from pathlib import Path
import re
import sys

REPOSITORY = Path(__file__).resolve().parents[4]
DIRECTORY = "qa/repository-consolidation/20261116/retained-evidence-parts"
MANIFEST = DIRECTORY + "/MANIFEST.json"
SCHEMA = "hepta.retained-evidence-parts.v1"
MAX_PART_BYTES = 500000
MAX_ORIGINAL_BYTES = 1048576
MAX_MANIFEST_BYTES = 131072

sys.path.insert(0, str(REPOSITORY / "scripts"))
from verify_source_custody_container import (
    canonical,
    identity,
    read_regular,
    require,
    unique_object,
)


def fingerprint(row):
    return {key: row[key] for key in ("bytes", "sha256", "oid")}


def verify(repository=REPOSITORY, document=None):
    """Return original bytes as data; do not execute or extract any source."""
    repository = Path(repository)
    if document is None:
        document = json.loads(
            read_regular(repository, MANIFEST, MAX_MANIFEST_BYTES),
            object_pairs_hook=unique_object,
        )
    require(
        document["schema"] == SCHEMA
        and document["part_limit_bytes"] == MAX_PART_BYTES
        and document["repository_blob_limit_bytes"] == 512000
        and document["source_executed"] is False
        and document["scientific_or_runtime_qualification"] is False,
        "evidence boundary or size policy changed",
    )
    rows = document["files"]
    require(isinstance(rows, list) and len(rows) == 6, "original file roster changed")
    original = {}
    part_count = 0
    for row in rows:
        path = canonical(row["path"])
        require(
            path.startswith("qualification/")
            and path not in original
            and row["mode"] == "100644"
            and type(row["bytes"]) is int
            and 512000 < row["bytes"] <= MAX_ORIGINAL_BYTES
            and re.fullmatch(r"[0-9a-f]{40}", row["oid"])
            and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]),
            "invalid original file identity",
        )
        sources = row["original_incoming_commits"]
        require(
            isinstance(sources, list)
            and 0 < len(sources) <= 27
            and all(re.fullmatch(r"[0-9a-f]{40}", value) for value in sources),
            "missing original history identity",
        )
        parts = row["parts"]
        require(isinstance(parts, list) and len(parts) == 2, "part roster changed")
        offset = 0
        payload = []
        for number, part in enumerate(parts, 1):
            name = canonical(part["path"])
            require(
                name == path + ".part-%03d" % number
                and part["offset"] == offset
                and type(part["bytes"]) is int
                and 0 < part["bytes"] <= MAX_PART_BYTES,
                "invalid part sequence, offset or size",
            )
            data = read_regular(repository, name, part["bytes"])
            require(identity(data) == fingerprint(part), "part identity mismatch")
            offset += len(data)
            payload.append(data)
            part_count += 1
        data = b"".join(payload)
        require(identity(data) == fingerprint(row), "original identity mismatch")
        index = json.loads(
            read_regular(repository, path + ".parts.json", MAX_MANIFEST_BYTES),
            object_pairs_hook=unique_object,
        )
        require(
            index["schema"] == SCHEMA
            and index["collection_manifest"] == MANIFEST
            and index["original"] == row,
            "asset index differs from collection",
        )
        original[path] = data
    controls = document["controls"]
    require(
        isinstance(controls, list) and len(controls) == 3,
        "original control roster changed",
    )
    for row in controls:
        path = canonical(row["path"])
        old = row["original"]
        copy = canonical(row["original_copy"])
        require(
            path.startswith("qualification/")
            and path not in original
            and copy == DIRECTORY + "/original-controls/" + old["oid"] + ".txt",
            "invalid original control path",
        )
        raw = read_regular(repository, copy, old["bytes"])
        current = read_regular(repository, path, row["current"]["bytes"])
        require(identity(raw) == fingerprint(old), "original control identity mismatch")
        require(
            identity(current) == fingerprint(row["current"]),
            "maintained control identity mismatch",
        )
        if row["kind"] == "readme-links":
            expected = raw
            for replacement in row["replacements"]:
                before = replacement["from"].encode()
                require(expected.count(before) == 1, "README link source changed")
                expected = expected.replace(before, replacement["to"].encode())
            require(current == expected, "README change exceeds recorded links")
        else:
            require(row["kind"] == "prettier-ast-equivalent", "unknown control change")
        original[path] = raw
    equivalence = document["codec_format_equivalence"]
    raw = read_regular(repository, equivalence["path"], equivalence["bytes"])
    require(identity(raw) == fingerprint(equivalence), "format receipt identity mismatch")
    receipt = json.loads(raw, object_pairs_hook=unique_object)
    require(
        receipt["normalized_ast_equal"] is True
        and receipt["original_source_executed"] is False
        and receipt["formatted_source_executed"] is False,
        "format equivalence boundary changed",
    )
    codec = [row for row in controls if row["kind"] == "prettier-ast-equivalent"]
    require(
        len(codec) == 1
        and receipt["original_path"] == codec[0]["path"]
        and receipt["original_sha256"] == codec[0]["original"]["sha256"]
        and receipt["formatted_sha256"] == codec[0]["current"]["sha256"]
        and receipt["prettier_version"] == "3.5.3",
        "format receipt does not bind the preserved and maintained codec",
    )
    return original, {
        "original_large_files": len(rows),
        "parts": part_count,
        "original_controls_preserved": len(controls),
        "restorable_bytes": sum(map(len, original.values())),
        "part_limit_bytes": MAX_PART_BYTES,
        "all_original_git_and_sha256_identities_match": True,
        "archived_source_executed": False,
        "scientific_or_runtime_qualification": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--restore-to",
        type=Path,
        help="create a new directory outside the repository with original relative paths",
    )
    args = parser.parse_args(argv)
    try:
        original, report = verify()
        if args.restore_to is not None:
            target = args.restore_to.resolve()
            require(
                not target.is_relative_to(REPOSITORY.resolve()),
                "restore outside the repository to retain the normal blob size cap",
            )
            target.mkdir(parents=True, exist_ok=False)
            for path, raw in original.items():
                output = target / path
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("xb") as handle:
                    handle.write(raw)
            report["restored_to"] = str(target)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("Evidence verification failed: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
