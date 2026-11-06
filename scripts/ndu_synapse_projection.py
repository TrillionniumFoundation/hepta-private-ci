"""Export an explicit diagnostic view while retaining the separate full artifact.

The view uses the original suffix rule minus four declared input/target trees.
Its completeness never means that the original full artifact is reconstructible.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import zlib


sys.dont_write_bytecode = True


COLLECTOR_SHA256 = "47867b1e884c29993524558020b4dcf3800910ae33dc00feb11b435081be0761"
EXCLUDED_PREFIXES = (
    "preparation/prefetch/cargo-home/",
    "qualification/build/cargo-home/",
    "qualification/build/cold-test/",
    "qualification/build/cold-product/",
)
MAX_CATALOGUE_FILES = 200000
MAX_CATALOGUE_BYTES = 64 * 1024 * 1024


class ProjectionError(Exception):
    """A fixed, locally defined projection failure reason."""


def require(condition, code):
    if not condition:
        raise ProjectionError(code)


def collector_module():
    path = Path(__file__).with_name("ndu_synapse_diagnostics.py")
    require(not path.is_symlink(), "COLLECTOR_LINK")
    require(
        hashlib.sha256(path.read_bytes()).hexdigest() == COLLECTOR_SHA256,
        "COLLECTOR_IDENTITY",
    )
    spec = importlib.util.spec_from_file_location("projection_collector", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns)


def category(name, suffixes):
    excluded = next((p for p in EXCLUDED_PREFIXES if name.startswith(p)), None)
    return excluded or ("selected" if Path(name).suffix in suffixes else "other-suffix")


def inventory(source, collector):
    def fail_walk(error):
        raise error

    require(source.is_dir() and not source.is_symlink(), "SOURCE_DIRECTORY")
    require(source.resolve(strict=True) == source, "SOURCE_PHYSICAL_PATH")
    files, selected, snapshots = [], {}, {".": signature(source.stat())}
    excluded = {
        p: {"entries": 0, "lstat_bytes": 0, "suffix_files": 0}
        for p in EXCLUDED_PREFIXES
    }
    total = 0
    for directory, folders, names in os.walk(
        source, followlinks=False, onerror=fail_walk
    ):
        folders.sort()
        for folder in folders:
            path = Path(directory) / folder
            relative = path.relative_to(source).as_posix()
            info = path.lstat()
            snapshots[relative + "/"] = signature(info)
            require(not stat.S_ISLNK(info.st_mode), "DIRECTORY_LINK")
        for name in sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(source).as_posix()
            require(len(relative.encode()) <= collector.MAX_PATH_BYTES, "PATH_BOUND")
            require(
                not any(ord(c) < 32 or ord(c) == 127 or c in "\\:" for c in relative),
                "UNSAFE_PATH",
            )
            info = path.lstat()
            kind = category(relative, collector.SUFFIXES)
            snapshots[relative] = signature(info)
            files.append(
                {
                    "path": relative,
                    "lstat_bytes": info.st_size,
                    "mode": info.st_mode,
                    "category": kind,
                }
            )
            require(len(files) <= MAX_CATALOGUE_FILES, "CATALOGUE_COUNT_BOUND")
            if kind in excluded:
                excluded[kind]["entries"] += 1
                excluded[kind]["lstat_bytes"] += info.st_size
                excluded[kind]["suffix_files"] += int(path.suffix in collector.SUFFIXES)
            if kind != "selected":
                continue
            require(stat.S_ISREG(info.st_mode), "SELECTED_NONREGULAR")
            require(len(selected) < collector.MAX_FILES, "SELECTED_FILE_BOUND")
            total += info.st_size
            require(
                total <= collector.PART_BYTES * collector.MAX_PARTS,
                "SELECTED_BYTE_BOUND",
            )
            selected[relative] = signature(info)
    raw = (
        json.dumps(sorted(files, key=lambda row: row["path"]), indent=2) + "\n"
    ).encode()
    require(len(raw) <= MAX_CATALOGUE_BYTES, "CATALOGUE_BYTE_BOUND")
    return selected, snapshots, raw, excluded


def read_file(source, relative, expected, destination=None):
    """Read the same regular file through directory descriptors without links."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(source, flags)
    try:
        parts = relative.split("/")
        for part in parts[:-1]:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    finally:
        os.close(directory)
    digest, crc, size = hashlib.sha256(), 0, 0
    with os.fdopen(descriptor, "rb") as incoming:
        require(
            signature(os.fstat(incoming.fileno())) == expected, "SOURCE_OPEN_CHANGED"
        )
        output = destination.open("xb") if destination is not None else None
        try:
            if output is not None:
                os.fchmod(output.fileno(), 0o600)
            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                size += len(block)
                require(size <= expected[3], "SOURCE_READ_GREW")
                digest.update(block)
                crc = zlib.crc32(block, crc)
                if output is not None:
                    output.write(block)
            require(
                signature(os.fstat(incoming.fileno())) == expected
                and size == expected[3],
                "SOURCE_READ_CHANGED",
            )
        finally:
            if output is not None:
                output.close()
    return {"bytes": size, "sha256": digest.hexdigest(), "crc32": f"{crc:08x}"}


def collect_projection(source, output, source_commit):
    source, output = Path(source).absolute(), Path(output).absolute()
    require(
        not output.resolve().is_relative_to(source.resolve()), "OUTPUT_INSIDE_SOURCE"
    )
    require(
        not source.resolve().is_relative_to(output.resolve()), "SOURCE_INSIDE_OUTPUT"
    )
    require(not output.exists() and not output.is_symlink(), "OUTPUT_ALREADY_EXISTS")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", source_commit)), "SOURCE_COMMIT_FORMAT")
    collector = collector_module()
    result = {
        "schema": "hepta.synapse.explicit-diagnostic-view.v1",
        "complete_projection": False,
        "source_commit": source_commit,
        "original_source_directory": str(source),
        "selection": {
            "suffixes": sorted(collector.SUFFIXES),
            "excluded_prefixes": list(EXCLUDED_PREFIXES),
        },
        "bounds": {
            "max_files": collector.MAX_FILES,
            "max_path_bytes": collector.MAX_PATH_BYTES,
            "part_bytes": collector.PART_BYTES,
            "max_parts": collector.MAX_PARTS,
        },
        "source_catalogue_scope": "All filesystem entries except ordinary directories; lstat metadata only for omitted entries, never followed links",
        "whole_original_artifact_restorable": False,
        "qualification_or_promotion": False,
        "full_artifact": {
            "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "expected_name": "ndu-native-synapse-arm64-"
            + os.environ.get("GITHUB_RUN_ID", "unbound")
            + "-"
            + os.environ.get("GITHUB_RUN_ATTEMPT", "unbound"),
            "archive_identity": "The separate unchanged upload runs later; its actual ZIP identity must be obtained from the artifact API, not inferred here.",
        },
        "files": {},
        "collector_called": False,
        "source_catalogue_complete": False,
    }
    try:
        selected, before, catalogue, excluded = inventory(source, collector)
        require(bool(selected), "EMPTY_PROJECTION")
        result["excluded_inventory"] = excluded
        with tempfile.TemporaryDirectory(
            prefix="ndu-diagnostic-view-", dir=output.parent
        ) as directory:
            view = Path(directory)
            for name, expected in sorted(selected.items()):
                destination = view / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                result["files"][name] = read_file(source, name, expected, destination)
            source_records = [
                view / name
                for name in ("CI_STARTED.json", "CI_RESULT.json")
                if (view / name).is_file()
            ]
            require(bool(source_records), "SOURCE_RECEIPT_MISSING")
            require(
                all(
                    json.loads(p.read_bytes()).get("source_commit") == source_commit
                    for p in source_records
                ),
                "SOURCE_RECEIPT_MISMATCH",
            )
            result["collector_called"] = True
            collected = collector.collect(view, output)
            require(collected["complete"], "ORIGINAL_COLLECTOR_REJECTED_VIEW")
            require(
                collected["files"]
                == {
                    name: {key: identity[key] for key in ("bytes", "sha256")}
                    for name, identity in result["files"].items()
                },
                "COLLECTOR_VIEW_CHANGED",
            )
            for name, expected in sorted(selected.items()):
                require(
                    read_file(source, name, expected) == result["files"][name],
                    "ORIGINAL_FILE_CHANGED",
                )
            after_selected, after, after_catalogue, after_excluded = inventory(
                source, collector
            )
            require(
                (selected, before, catalogue, excluded)
                == (after_selected, after, after_catalogue, after_excluded),
                "ORIGINAL_INVENTORY_CHANGED",
            )
            (output / "SOURCE_DIRECTORY.json").write_bytes(catalogue)
            result.update(
                complete_projection=True,
                original_selected_files_unchanged=True,
                source_catalogue_complete=True,
                source_catalogue={
                    "bytes": len(catalogue),
                    "sha256": hashlib.sha256(catalogue).hexdigest(),
                },
                original_collector_sha256=COLLECTOR_SHA256,
                diagnostics={
                    "bytes": (output / "DIAGNOSTICS.json").stat().st_size,
                    "sha256": hashlib.sha256(
                        (output / "DIAGNOSTICS.json").read_bytes()
                    ).hexdigest(),
                },
            )
    except Exception as error:
        result["complete_projection"] = False
        result["error"] = {"type": type(error).__name__}
        if isinstance(error, ProjectionError):
            result["error"]["code"] = str(error)
    finally:
        output.mkdir(parents=True, exist_ok=True)
        (output / "PROJECTION.json").write_text(json.dumps(result, indent=2) + "\n")
        if not result["collector_called"] and (
            github_output := os.environ.get("GITHUB_OUTPUT")
        ):
            with Path(github_output).open("a") as stream:
                stream.write("part_count=0\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    result = collect_projection(args.source, args.output, args.source_commit)
    print(
        json.dumps(
            {
                "complete_projection": result["complete_projection"],
                "selected_files": len(result["files"]),
                "qualification_or_promotion": False,
            }
        )
    )
    return 0 if result["complete_projection"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
