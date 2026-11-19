#!/usr/bin/env python3
"""Verify and restore exact Cell research bytes retained by merge-parent history."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys

DIRECTORY = Path(__file__).resolve().parent
REPOSITORY = DIRECTORY.parents[3]
SCHEMA = "hepta.cell-history-custody.v1"
SNAPSHOT_SCHEMA = "hepta.cell-history-snapshot.v1"
CURRENT_INPUT_SCHEMA = "hepta.cell-current-inputs.v1"
MAX_INDEX_BYTES = 500000
MAX_SNAPSHOT_INDEX_BYTES = 2000000
MAX_BLOB_BYTES = 16 * 1024 * 1024
MAX_FILES = 1300
MAX_TOTAL_BYTES = 250000000
PREFIXES = ("qa/stem-bakeoff", "qa/evidence/cell-field/v8")
SOURCE_SUFFIXES = (".py", ".sh", ".rs", ".js", ".ts", ".tsx", ".jsx", ".pyc")
FROZEN_TEXT_CORPORA = frozenset({
    "qa/stem-bakeoff/evidence/20261024-cell-parameter-field-v2/data/predictors.json",
    "qa/stem-bakeoff/evidence/20261024-cell-parameter-field-v3/data/predictors.json",
})


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def canonical(value):
    require(type(value) is str and 0 < len(value.encode()) <= 2048, "invalid path")
    path = PurePosixPath(value)
    require(
        not path.is_absolute()
        and path.as_posix() == value
        and ".." not in path.parts
        and "." not in path.parts
        and "\\" not in value
        and ":" not in value
        and all(ord(char) >= 32 for char in value),
        "noncanonical or escaping path",
    )
    return value


def identity(data):
    header = b"blob " + str(len(data)).encode() + b"\0"
    return {
        "bytes": len(data),
        "oid": hashlib.sha1(header + data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def fingerprint(row):
    return {key: row[key] for key in ("bytes", "oid", "sha256")}


def read_regular(path, maximum):
    path = Path(path)
    require(not path.is_symlink(), "metadata must not be a symbolic link")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(details.st_mode) and 0 <= details.st_size <= maximum,
            "metadata type or size exceeds the bound",
        )
        data = stream.read(maximum + 1)
    require(len(data) == details.st_size and len(data) <= maximum, "metadata changed")
    return data


def git(repository, *arguments, payload=None):
    environment = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_OPTIONAL_LOCKS="0")
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repository), *arguments],
        input=payload,
        capture_output=True,
        env=environment,
        timeout=60,
    )
    require(result.returncode == 0, "required Git object or history is unavailable")
    return result.stdout


def validate_row(row):
    path = canonical(row["path"])
    require(
        any(path.startswith(prefix + "/") for prefix in PREFIXES)
        and row["mode"] in ("100644", "100755")
        and type(row["bytes"]) is int
        and 0 <= row["bytes"] <= MAX_BLOB_BYTES
        and type(row["oid"]) is str
        and re.fullmatch(r"[0-9a-f]{40}", row["oid"]) is not None
        and type(row["sha256"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None,
        "invalid bounded file identity",
    )
    return path


def read_blob(repository, row):
    validate_row(row)
    oid = row["oid"]
    details = git(
        repository, "cat-file", "--batch-check", payload=(oid + "\n").encode()
    ).decode().split()
    require(details == [oid, "blob", str(row["bytes"])], "Git blob type or size differs")
    data = git(repository, "cat-file", "blob", oid)
    require(identity(data) == fingerprint(row), "Git or SHA256 byte identity differs")
    return data


def tree_entries(repository, commit, prefix):
    raw = git(repository, "ls-tree", "-r", "-z", commit, "--", prefix)
    rows = {}
    for item in raw.split(b"\0"):
        if not item:
            continue
        metadata, name = item.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        path = canonical(name.decode("utf-8"))
        require(kind == "blob" and mode in ("100644", "100755"), "unsupported tree entry")
        require(path not in rows, "duplicate Git tree path")
        rows[path] = {"mode": mode, "oid": oid}
    return rows


def validate_document(document):
    require(
        document["schema"] == SCHEMA
        and document["repository_blob_limit_bytes"] == 512000
        and document["archived_source_executed_by_restorer"] is False
        and document["scientific_or_runtime_qualification"] is False,
        "history custody or policy boundary changed",
    )
    parents = document["required_original_merge_parents"]
    require(
        isinstance(parents, list)
        and 1 <= len(parents) <= 2
        and len(set(parents)) == len(parents)
        and all(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) for value in parents),
        "invalid original parent roster",
    )
    rows = document["assets"]
    require(isinstance(rows, list) and 0 < len(rows) <= 256, "asset roster exceeds bound")
    seen = set()
    total = 0
    for row in rows:
        path = validate_row(row)
        sources = row["source_commits"]
        require(
            path not in seen
            and (
                (row["custody_reason"] == "over_original_blob_size_limit"
                 and row["bytes"] > document["repository_blob_limit_bytes"])
                or (row["custody_reason"] == "original_dataset_text"
                    and path in FROZEN_TEXT_CORPORA
                    and 0 < row["bytes"] <= document["repository_blob_limit_bytes"])
            )
            and isinstance(sources, list)
            and 0 < len(sources) <= len(parents)
            and len(set(sources)) == len(sources)
            and all(source in parents for source in sources),
            "duplicate asset or invalid source binding",
        )
        seen.add(path)
        total += row["bytes"]
    require(
        type(document["asset_count"]) is int
        and document["asset_count"] == len(rows)
        and type(document["asset_total_bytes"]) is int
        and document["asset_total_bytes"] == total
        and total <= MAX_TOTAL_BYTES,
        "asset count or total byte bound differs",
    )
    return parents


def require_retained_history(repository, document, head=None):
    parents = validate_document(document)
    if head is None:
        head = git(repository, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    require(type(head) is str and re.fullmatch(r"[0-9a-f]{40}", head), "full head SHA required")
    require(git(repository, "cat-file", "-t", head) == b"commit\n", "head is not a commit")
    for parent in parents:
        git(repository, "merge-base", "--is-ancestor", parent, head)
    return head


def validate_asset_paths(repository, document):
    parent_entries = {}
    for parent in document["required_original_merge_parents"]:
        entries = {}
        for prefix in PREFIXES:
            entries.update(tree_entries(repository, parent, prefix))
        parent_entries[parent] = entries
    for row in document["assets"]:
        expected = {"mode": row["mode"], "oid": row["oid"]}
        for source in row["source_commits"]:
            require(
                parent_entries[source].get(row["path"]) == expected,
                "original commit and exact asset path do not bind the blob",
            )


def snapshot_rows(repository, document, name, directory=DIRECTORY):
    references = document["snapshots"]
    selected = [row for row in references if row["name"] == name]
    require(len(selected) == 1, "unknown or duplicated snapshot name")
    reference = selected[0]
    source = reference["source_commit"]
    require(source in document["required_original_merge_parents"], "snapshot parent is not retained")
    relative = canonical(reference["manifest_path"])
    require(relative == "snapshots/" + name + ".json.gz", "unexpected snapshot metadata path")
    compressed = read_regular(Path(directory) / relative, MAX_INDEX_BYTES)
    require(identity(compressed) == reference["compressed"], "compressed snapshot index changed")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw = stream.read(MAX_SNAPSHOT_INDEX_BYTES + 1)
    require(
        len(raw) <= MAX_SNAPSHOT_INDEX_BYTES and identity(raw) == reference["uncompressed"],
        "snapshot index size or byte identity changed",
    )
    snapshot = json.loads(raw, object_pairs_hook=unique_object)
    require(
        snapshot["schema"] == SNAPSHOT_SCHEMA
        and snapshot["name"] == name
        and snapshot["source_commit"] == source
        and snapshot["roots"] == reference["roots"],
        "snapshot source identity differs",
    )
    rows = snapshot["files"]
    require(isinstance(rows, list) and 0 < len(rows) <= MAX_FILES, "snapshot roster exceeds bound")
    actual = {}
    roots = snapshot["roots"]
    require(isinstance(roots, list) and 0 < len(roots) <= len(PREFIXES), "invalid snapshot roots")
    seen_roots = set()
    for root in roots:
        prefix = canonical(root["path"])
        require(prefix in PREFIXES and prefix not in seen_roots, "unexpected snapshot root")
        seen_roots.add(prefix)
        oid = git(repository, "rev-parse", source + ":" + prefix).decode().strip()
        require(oid == root["tree"], "snapshot subtree differs")
        actual.update(tree_entries(repository, source, prefix))
    wanted = {}
    total = 0
    for row in rows:
        path = validate_row(row)
        require(path not in wanted, "duplicate snapshot path")
        wanted[path] = {"mode": row["mode"], "oid": row["oid"]}
        total += row["bytes"]
    require(
        wanted == actual
        and type(snapshot["file_count"]) is int
        and snapshot["file_count"] == reference["file_count"] == len(rows)
        and type(snapshot["total_bytes"]) is int
        and snapshot["total_bytes"] == reference["total_bytes"] == total
        and total <= MAX_TOTAL_BYTES,
        "snapshot file closure or total byte bound differs",
    )
    return rows


def current_input_rows(repository, document, head, directory=DIRECTORY):
    reference = document["current_inputs"]
    require(
        reference["manifest_path"] == "current-inputs.json.gz"
        and reference["excluded_source_suffixes"] == list(SOURCE_SUFFIXES),
        "current input metadata or source exclusion changed",
    )
    compressed = read_regular(Path(directory) / reference["manifest_path"], MAX_INDEX_BYTES)
    require(identity(compressed) == reference["compressed"], "compressed current input index changed")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw = stream.read(MAX_SNAPSHOT_INDEX_BYTES + 1)
    require(
        len(raw) <= MAX_SNAPSHOT_INDEX_BYTES and identity(raw) == reference["uncompressed"],
        "current input index size or identity changed",
    )
    index = json.loads(raw, object_pairs_hook=unique_object)
    require(
        index["schema"] == CURRENT_INPUT_SCHEMA
        and index["roots"] == reference["roots"]
        and index["excluded_source_suffixes"] == list(SOURCE_SUFFIXES),
        "current input declaration changed",
    )
    roots = index["roots"]
    require(isinstance(roots, list) and 0 < len(roots) <= 12, "invalid current input roots")
    actual = {}
    seen_roots = set()
    for prefix in roots:
        canonical(prefix)
        require(
            any(prefix.startswith(parent + "/") for parent in PREFIXES)
            and prefix not in seen_roots
            and not any(prefix.startswith(parent + "/") or parent.startswith(prefix + "/")
                        for parent in seen_roots),
            "unexpected or overlapping current input roots",
        )
        seen_roots.add(prefix)
        actual.update({
            path: entry for path, entry in tree_entries(repository, head, prefix).items()
            if not path.endswith(SOURCE_SUFFIXES)
        })
    rows = index["files"]
    require(isinstance(rows, list) and 0 < len(rows) <= MAX_FILES, "current input roster exceeds bound")
    assets = {row["path"]: row for row in document["assets"]}
    wanted = {}
    total = 0
    for row in rows:
        path = validate_row(row)
        require(
            path not in wanted and not path.endswith(SOURCE_SUFFIXES)
            and any(path.startswith(root + "/") for root in roots),
            "duplicate, source, or out-of-root current input",
        )
        wanted[path] = {"mode": row["mode"], "oid": row["oid"]}
        if path in assets:
            require(
                fingerprint(row) == fingerprint(assets[path])
                and row["mode"] == assets[path]["mode"]
                and path not in actual,
                "historical asset identity or maintained representation changed",
            )
        total += row["bytes"]
    require(set(assets).issubset(wanted), "current input closure omits a historical asset")
    retained = {path: entry for path, entry in wanted.items() if path not in assets}
    require(
        retained == actual
        and type(index["file_count"]) is int
        and index["file_count"] == reference["file_count"] == len(rows)
        and type(index["total_bytes"]) is int
        and index["total_bytes"] == reference["total_bytes"] == total
        and total <= MAX_TOTAL_BYTES,
        "current input file closure or byte bound differs from the maintained head",
    )
    return rows


def verify(repository, document, head=None, snapshot=None, directory=DIRECTORY,
           current_inputs=False):
    head = require_retained_history(repository, document, head)
    validate_asset_paths(repository, document)
    require(not (snapshot is not None and current_inputs), "select one restoration mode")
    if current_inputs:
        rows = current_input_rows(repository, document, head, directory)
    elif snapshot is not None:
        rows = snapshot_rows(repository, document, snapshot, directory)
    else:
        rows = document["assets"]
    for row in rows:
        read_blob(repository, row)
    return rows, {
        "head": head,
        "required_original_parents_retained": document["required_original_merge_parents"],
        "verified_files": len(rows),
        "verified_bytes": sum(row["bytes"] for row in rows),
        "snapshot": snapshot,
        "current_input_tree_verified_against_head": current_inputs,
        "all_git_and_sha256_identities_match": True,
        "archived_source_executed": False,
        "scientific_or_runtime_qualification": False,
    }


def restore(repository, rows, destination):
    repository = Path(git(repository, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    requested = Path(destination).absolute()
    require(not requested.exists() and not requested.is_symlink(), "new restoration directory required")
    destination = requested.resolve()
    require(
        not destination.is_relative_to(repository),
        "restore outside the repository to preserve the maintained blob size policy",
    )
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    for row in rows:
        path = validate_row(row)
        data = read_blob(repository, row)
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        require(target.parent.resolve().is_relative_to(destination), "restoration parent escaped")
        with target.open("xb") as stream:
            stream.write(data)
        target.chmod(0o755 if row["mode"] == "100755" else 0o644)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=REPOSITORY)
    parser.add_argument("--head", help="full commit SHA for an unpublished merge candidate")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--snapshot", choices=("cell-v4", "cell-v8"))
    mode.add_argument("--current-inputs", action="store_true",
                      help="restore complete maintained input directories without copying source")
    parser.add_argument(
        "--restore-to", type=Path, help="new directory outside the repository"
    )
    args = parser.parse_args(argv)
    try:
        raw = read_regular(DIRECTORY / "MANIFEST.json", MAX_INDEX_BYTES)
        document = json.loads(raw, object_pairs_hook=unique_object)
        rows, report = verify(
            args.repository, document, args.head, args.snapshot, DIRECTORY,
            current_inputs=args.current_inputs
        )
        if args.restore_to is not None:
            report["restored_to"] = str(restore(args.repository, rows, args.restore_to))
    except (OSError, EOFError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print("History custody verification failed: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
