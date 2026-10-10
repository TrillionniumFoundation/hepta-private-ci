#!/usr/bin/env python3
"""Read-only, exact-commit integration diagnostics; never a qualification receipt.

Conflicts are retained with NUL-safe paths and exact Git blob identities. Source
archives are optional review inputs, not replacement commits or executed trees.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

OID = re.compile(r"[0-9a-f]{40}\Z")
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


def git(
    root: Path, *args: str, allowed: tuple[int, ...] = (0,)
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "--no-replace-objects", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode not in allowed:
        raise ValueError(
            f"git {args[0]} exited {result.returncode}: "
            + result.stderr.decode("utf-8", "replace")[:4000]
        )
    if len(result.stdout) > MAX_OUTPUT_BYTES:
        raise ValueError(f"git {args[0]} output exceeds the diagnostic bound")
    return result


def object_id(value: str) -> str:
    if not OID.fullmatch(value):
        raise ValueError("an exact 40-character Git object identity is required")
    return value


def parse_merge(output: bytes) -> tuple[str, list[dict[str, object]]]:
    """Parse only the typed stage section, never human-readable conflict text."""
    fields = output.split(b"\0")
    tree = object_id(fields[0].decode("ascii"))
    stages = []
    for field in fields[1:]:
        if not field:
            break
        header, path = field.split(b"\t", 1)
        mode, oid, stage = header.decode("ascii").split(" ")
        if mode not in {"100644", "100755", "120000", "160000"} or stage not in {
            "1",
            "2",
            "3",
        }:
            raise ValueError("invalid merge stage entry")
        stages.append(
            {
                "path": path.decode("utf-8", "strict"),
                "mode": mode,
                "object": object_id(oid),
                "stage": int(stage),
            }
        )
    return tree, stages


def diagnose(root: Path, source: str, target: str) -> dict:
    source, target = object_id(source), object_id(target)
    for commit in (source, target):
        if git(root, "cat-file", "-t", commit).stdout.strip() != b"commit":
            raise ValueError("diagnostic identities must be commits")
    if git(root, "rev-parse", "HEAD").stdout.decode().strip() != source:
        raise ValueError("the checkout is not the exact source commit")
    git(root, "diff", "--no-ext-diff", "--no-textconv", "--exit-code", "HEAD", "--")
    git(
        root,
        "diff",
        "--cached",
        "--no-ext-diff",
        "--no-textconv",
        "--exit-code",
        "HEAD",
        "--",
    )
    base = object_id(git(root, "merge-base", source, target).stdout.decode().strip())
    merged = git(
        root,
        "merge-tree",
        "--write-tree",
        "--messages",
        "-z",
        source,
        target,
        allowed=(0, 1),
    )
    tree, stages = parse_merge(merged.stdout)
    # One recursive raw diff gives both the changed paths and their exact
    # destination objects. Do not spawn a separate ls-tree for every path: a
    # large integration must not pay one extra Git process per changed file.
    raw = git(
        root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--raw",
        "--no-abbrev",
        "--no-renames",
        "-z",
        source,
        tree,
        "--",
    ).stdout
    fields = raw.split(b"\0")
    if fields[-1] != b"" or len(fields) % 2 != 1:
        raise ValueError("invalid raw tree diff framing")
    entries = []
    for offset in range(0, len(fields) - 1, 2):
        header, path_bytes = fields[offset : offset + 2]
        parts = header.decode("ascii").split(" ")
        if len(parts) != 5 or not parts[0].startswith(":") or not path_bytes:
            raise ValueError("invalid raw tree diff entry")
        old_mode, mode, old_oid, oid, status = parts
        modes = {"000000", "100644", "100755", "120000", "160000"}
        if (
            old_mode[1:] not in modes
            or mode not in modes
            or status not in {"A", "D", "M", "T"}
        ):
            raise ValueError("invalid raw tree diff mode or status")
        object_id(old_oid)
        object_id(oid)
        path = path_bytes.decode("utf-8", "strict")
        if status == "D":
            if mode != "000000" or oid != "0" * 40:
                raise ValueError("deleted entry still has a destination object")
            entries.append({"path": path, "deleted": True})
        else:
            if mode == "000000" or oid == "0" * 40:
                raise ValueError("live entry has no destination object")
            kind = "commit" if mode == "160000" else "blob"
            entries.append({"path": path, "mode": mode, "type": kind, "object": oid})
    return {
        "source": source,
        "target": target,
        "base": base,
        "source_tree": object_id(
            git(root, "rev-parse", source + "^{tree}").stdout.decode().strip()
        ),
        "target_tree": object_id(
            git(root, "rev-parse", target + "^{tree}").stdout.decode().strip()
        ),
        "merge_tree": tree,
        "mergeable": merged.returncode == 0,
        "conflicts": sorted({stage["path"] for stage in stages}),
        "stages": stages,
        "entries": entries,
        "qualification": False,
    }


def retain(root: Path, output: Path, report: dict, archives: bool = False) -> None:
    output.mkdir(parents=True, exist_ok=False)
    (output / "integration.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    # Name blobs by validated object ID, not by untrusted repository path.
    blobs = output / "conflict-blobs"
    blobs.mkdir()
    for stage in report["stages"]:
        oid = stage["object"]
        if stage["mode"] != "160000" and not (blobs / oid).exists():
            (blobs / oid).write_bytes(git(root, "cat-file", "blob", oid).stdout)
    if archives:
        for label in ("source", "target", "base"):
            path = output / f"{label}.tar.gz"
            # git archive contains only committed source, never .git/config,
            # checkout credentials, untracked build files, or a rewritten tree.
            with path.open("xb") as stream:
                result = subprocess.run(
                    [
                        "git",
                        "--no-replace-objects",
                        "archive",
                        "--format=tar.gz",
                        report[label],
                    ],
                    cwd=root,
                    stdout=stream,
                    stderr=subprocess.PIPE,
                    timeout=120,
                )
            if result.returncode or path.stat().st_size > MAX_ARCHIVE_BYTES:
                path.unlink(missing_ok=True)
                raise ValueError(f"{label} archive failed or exceeded the size bound")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--archives", action="store_true")
    args = parser.parse_args()
    try:
        report = diagnose(args.root, args.source, args.target)
        retain(args.root, args.output, report, args.archives)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["mergeable"] else 1
    except (ValueError, OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        print(f"integration diagnostics failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
