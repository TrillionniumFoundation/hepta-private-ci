#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MAX_BYTES = 500 * 1024


@dataclass(frozen=True)
class ChangedBlob:
    path: str
    size_bytes: int
    is_allowlisted: bool
    is_binary: bool


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def load_allowlist(path: Path) -> dict[str, str | None]:
    allowlist: dict[str, str | None] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        expected_sha256 = None
        if line.startswith("sha256:"):
            parts = line.split(maxsplit=1)
            if (
                len(parts) != 2
                or re.fullmatch(r"sha256:[0-9a-f]{64}", parts[0]) is None
            ):
                raise ValueError(f"{path}:{number}: malformed SHA-256 asset pin")
            expected_sha256 = parts[0].removeprefix("sha256:")
            line = parts[1]
        if line in allowlist and allowlist[line] != expected_sha256:
            raise ValueError(f"{path}:{number}: conflicting asset entries for {line}")
        allowlist[line] = expected_sha256
    return allowlist


def is_blob_allowlisted(
    commit: str, path: str, allowlist: dict[str, str | None]
) -> bool:
    if path not in allowlist:
        return False
    expected_sha256 = allowlist[path]
    if expected_sha256 is None:
        return True
    data = subprocess.check_output(["git", "cat-file", "blob", f"{commit}:{path}"])
    return hashlib.sha256(data).hexdigest() == expected_sha256


def get_changed_paths(base: str, head: str) -> list[str]:
    output = run_git(
        "diff",
        "--name-only",
        "--diff-filter=AM",
        "--no-renames",
        "-z",
        base,
        head,
    )
    return [path for path in output.split("\0") if path]


def is_binary_change(base: str, head: str, path: str) -> bool:
    output = run_git(
        "diff",
        "--numstat",
        "--diff-filter=AM",
        "--no-renames",
        base,
        head,
        "--",
        path,
    ).strip()
    if not output:
        return False

    added, deleted, _ = output.split("\t", 2)
    return added == "-" and deleted == "-"


def blob_size(commit: str, path: str) -> int:
    return int(run_git("cat-file", "-s", f"{commit}:{path}").strip())


def collect_changed_blobs(
    base: str, head: str, allowlist: dict[str, str | None]
) -> list[ChangedBlob]:
    # Read each diff once. Starting a separate Git diff for every path makes a
    # large history consolidation quadratic in the number of changed files.
    # NUL separators preserve literal tabs, newlines, and non-ASCII path names.
    raw = run_git(
        "diff",
        "--raw",
        "--no-abbrev",
        "--diff-filter=AM",
        "--no-renames",
        "-z",
        base,
        head,
    ).split("\0")
    if raw[-1] != "" or (len(raw) - 1) % 2:
        raise ValueError("Malformed Git changed-object inventory")
    objects: dict[str, str] = {}
    for index in range(0, len(raw) - 1, 2):
        header, path = raw[index : index + 2]
        fields = header.split()
        if len(fields) != 5 or not fields[0].startswith(":") or path in objects:
            raise ValueError("Malformed or duplicate Git changed-object record")
        objects[path] = fields[3]
    if not objects:
        return []

    object_ids = list(dict.fromkeys(objects.values()))
    result = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objectsize)"],
        input="\n".join(object_ids) + "\n",
        check=True,
        capture_output=True,
        text=True,
    )
    sizes: dict[str, int] = {}
    records = result.stdout.splitlines()
    if len(records) != len(object_ids):
        raise ValueError("Incomplete Git object-size inventory")
    for expected, record in zip(object_ids, records, strict=True):
        actual, size = record.split()
        if actual != expected or not size.isdecimal():
            raise ValueError("Missing or mismatched Git object size")
        sizes[actual] = int(size)

    binary: dict[str, bool] = {}
    numstat = run_git(
        "diff",
        "--numstat",
        "--diff-filter=AM",
        "--no-renames",
        "-z",
        base,
        head,
    )
    for record in numstat.split("\0"):
        if not record:
            continue
        added, deleted, path = record.split("\t", 2)
        if path in binary:
            raise ValueError("Duplicate Git numeric-diff record")
        binary[path] = added == "-" and deleted == "-"
    if objects.keys() != binary.keys():
        raise ValueError("Git changed-object and numeric-diff inventories differ")
    return [
        ChangedBlob(
            path=path,
            size_bytes=sizes[oid],
            is_allowlisted=is_blob_allowlisted(head, path, allowlist),
            is_binary=binary[path],
        )
        for path, oid in objects.items()
    ]


def format_kib(size_bytes: int) -> str:
    return f"{size_bytes / 1024:.1f} KiB"


def summary_path(path: str) -> str:
    escaped = path.replace("\r", "\\r").replace("\n", "\\n")
    escaped = escaped.replace("`", "\\`").replace("|", "\\|")
    encoded = escaped.encode("utf-8")
    if len(encoded) <= 512:
        return escaped
    return encoded[:509].decode("utf-8", errors="ignore") + "..."


def write_step_summary(
    max_bytes: int,
    blobs: list[ChangedBlob],
    violations: list[ChangedBlob],
) -> None:
    summary_path_value = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path_value:
        return

    lines = [
        "## Blob Size Policy",
        "",
        f"Default max: `{max_bytes}` bytes ({format_kib(max_bytes)})",
        f"Changed files checked: `{len(blobs)}`",
        f"Violations: `{len(violations)}`",
        f"Allowlisted files: `{sum(blob.is_allowlisted for blob in blobs)}`",
        "",
    ]

    displayed = violations[:20]
    if displayed:
        lines.extend(
            [
                "| Path | Kind | Size | Status |",
                "| --- | --- | ---: | --- |",
            ]
        )
        for blob in displayed:
            kind = "binary" if blob.is_binary else "non-binary"
            lines.append(
                f"| `{summary_path(blob.path)}` | {kind} | "
                f"`{blob.size_bytes}` bytes ({format_kib(blob.size_bytes)}) | blocked |"
            )
        lines.extend(
            [
                "",
                f"Showing {len(displayed)} of {len(violations)} violations.",
            ]
        )
    elif blobs:
        lines.append("No violations were detected.")
    else:
        lines.append("No changed files were detected.")

    lines.extend(
        [
            "",
            "The full checked-file list and every violation remain in the step log.",
            "Only this summary is sampled; the size decision checks every changed file.",
            "",
        ]
    )
    Path(summary_path_value).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail if changed blobs exceed the configured size budget."
    )
    parser.add_argument(
        "--base", required=True, help="Base git revision to diff against."
    )
    parser.add_argument("--head", required=True, help="Head git revision to inspect.")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help=f"Maximum allowed blob size in bytes. Default: {DEFAULT_MAX_BYTES}.",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        required=True,
        help="Exact paths, optionally prefixed with sha256:<digest>, one per line.",
    )
    args = parser.parse_args()

    try:
        allowlist = load_allowlist(args.allowlist)
    except ValueError as error:
        parser.error(str(error))
    blobs = collect_changed_blobs(args.base, args.head, allowlist)
    violations = [
        blob
        for blob in blobs
        if blob.size_bytes > args.max_bytes and not blob.is_allowlisted
    ]

    write_step_summary(args.max_bytes, blobs, violations)

    if not blobs:
        print("No changed files were detected.")
        return 0

    print(
        f"Checked {len(blobs)} changed file(s) against the {args.max_bytes}-byte limit."
    )
    for blob in blobs:
        status = "allowlisted" if blob.is_allowlisted else "ok"
        if blob in violations:
            status = "blocked"
        kind = "binary" if blob.is_binary else "non-binary"
        print(
            f"- {blob.path}: {blob.size_bytes} bytes ({format_kib(blob.size_bytes)}) [{kind}, {status}]"
        )

    if violations:
        print("\nFile(s) exceed the configured limit:")
        for blob in violations:
            print(f"- {blob.path}: {blob.size_bytes} bytes > {args.max_bytes} bytes")
        print(
            "\nIf one of these is a real checked-in asset we want to keep, add its "
            "repo-relative path to .github/blob-size-allowlist.txt. Otherwise, "
            "shrink it or keep it out of git."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
