#!/usr/bin/env python3
"""Emit fail-closed tracked-source provenance for channel.matrix qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import channel_matrix_evidence_v2 as policy

ROOT = SCRIPT_DIRECTORY.parent
SOURCE_ROOTS = tuple(policy.evidence.SOURCE_ROOTS)
SHA1 = re.compile(r"[0-9a-f]{40}")


def git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )


def split_z(value: bytes) -> list[str]:
    return [item.decode("utf-8") for item in value.split(b"\0") if item]


def aggregate(rows: list[dict[str, Any]]) -> str:
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(b"hepta.channel-matrix-source-provenance.v1\0" + encoded).hexdigest()


def runner_image() -> str:
    image_os = os.environ.get("ImageOS")
    image_version = os.environ.get("ImageVersion")
    if image_os and image_version:
        return f"{image_os}:{image_version}"
    runner_os = os.environ.get("RUNNER_OS")
    runner_arch = os.environ.get("RUNNER_ARCH")
    if runner_os and runner_arch:
        return f"{runner_os}/{runner_arch}"
    return "local-unreported"


def target_triple() -> str:
    configured = os.environ.get("RUST_HOST_TARGET")
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["rustc", "-vV"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    for line in result.stdout.splitlines():
        if line.startswith("host: "):
            return line.removeprefix("host: ")
    return "unavailable"


def clean_state(root: Path) -> dict[str, Any]:
    unstaged = split_z(git(root, "diff", "--name-only", "-z", "HEAD", "--").stdout)
    staged = split_z(git(root, "diff", "--cached", "--name-only", "-z", "HEAD", "--").stdout)
    untracked = split_z(
        git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", *SOURCE_ROOTS).stdout
    )
    ignored = split_z(
        git(
            root,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
            "--",
            *SOURCE_ROOTS,
        ).stdout
    )
    return {
        "clean": not (unstaged or staged or untracked or ignored),
        "unstaged": unstaged,
        "staged": staged,
        "untrackedClosureInputs": untracked,
        "ignoredClosureInputs": ignored,
    }


def classify(relative: str) -> dict[str, bool]:
    parts = Path(relative).parts
    return {
        "fixture": "fixtures" in parts or relative.startswith("scripts/tests/"),
        "workflow": relative.startswith(".github/workflows/"),
        "documentation": relative.startswith("docs/"),
        "generated": False,
        "cache": False,
        "artifact": False,
    }


def build(root_value: Path, expected_sha: str, stage: str) -> dict[str, Any]:
    root = root_value.resolve(strict=True)
    errors: list[str] = []
    if not SHA1.fullmatch(expected_sha):
        errors.append("expected SHA is not exact lowercase 40-hex")
    head = git(root, "rev-parse", "HEAD").stdout.decode().strip()
    tree = git(root, "rev-parse", "HEAD^{tree}").stdout.decode().strip()
    if head != expected_sha:
        errors.append("checkout HEAD differs from expected SHA")
    before = clean_state(root)
    if not before["clean"]:
        errors.append("checkout was not clean before source scan")

    all_tracked = split_z(git(root, "ls-files", "-z").stdout)
    closure = split_z(git(root, "ls-files", "-z", "--", *SOURCE_ROOTS).stdout)
    tracked_set = set(all_tracked)
    rows: list[dict[str, Any]] = []
    for relative in closure:
        absolute = root / relative
        unmatched = git(root, "ls-files", "--error-unmatch", "--", relative, check=False)
        tracked = relative in tracked_set and unmatched.returncode == 0
        if not tracked:
            errors.append(f"source input is not tracked: {relative}")
            continue
        if absolute.is_symlink() or not absolute.is_file():
            errors.append(f"source input is not a regular file: {relative}")
            continue
        data = absolute.read_bytes()
        committed = git(root, "show", f"{head}:{relative}", check=False)
        if committed.returncode != 0 or committed.stdout != data:
            errors.append(f"source input differs from committed bytes: {relative}")
            continue
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        resolved_blob = git(root, "rev-parse", f"{head}:{relative}").stdout.decode().strip()
        if blob != resolved_blob:
            errors.append(f"Git blob identity mismatch: {relative}")
            continue
        rows.append(
            {
                "absolutePath": str(absolute),
                "repoRelativePath": relative,
                "gitBlob": blob,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "tracked": True,
                "gitLsFilesErrorUnmatch": True,
                "firstObservedStage": stage,
                "origin": "tracked_repository_source",
                "classification": classify(relative),
            }
        )
    if not rows:
        errors.append("source closure inventory is empty")
    after = clean_state(root)
    if not after["clean"]:
        errors.append("checkout was not clean after source scan")
    return {
        "schema": "hepta.channel-matrix-source-provenance.v1",
        "valid": not errors,
        "errors": errors,
        "stage": stage,
        "workspaceRoot": str(root),
        "checkoutSha": head,
        "checkoutTree": tree,
        "scan": {
            "defaultCommand": ["git", "ls-files", "-z"],
            "closureCommand": ["git", "ls-files", "-z", "--", *SOURCE_ROOTS],
            "trackedFileCount": len(all_tracked),
            "closureFileCount": len(rows),
            "sourceRoots": list(SOURCE_ROOTS),
            "cleanBefore": before,
            "cleanAfter": after,
            "generatedInputs": [],
            "cacheInputs": [],
            "artifactInputs": [],
        },
        "execution": {
            "workflowRunId": os.environ.get("GITHUB_RUN_ID"),
            "attemptId": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "runnerImage": runner_image(),
            "runnerName": os.environ.get("RUNNER_NAME", "local-unreported"),
            "runnerOS": os.environ.get("RUNNER_OS", "local-unreported"),
            "runnerArch": os.environ.get("RUNNER_ARCH", "local-unreported"),
            "targetTriple": target_triple(),
        },
        "files": rows,
        "sourceInventorySha256": aggregate(rows),
        "claims": {
            "trackedSourceOnly": not errors,
            "generatedSourceIncluded": False,
            "cacheSourceIncluded": False,
            "artifactSourceIncluded": False,
            "authorityGranted": False,
        },
    }


def write_output(path_value: Path, row: dict[str, Any]) -> None:
    path = path_value.absolute()
    parent = path.parent.resolve(strict=True)
    if path_value.is_symlink() or parent.is_relative_to(ROOT.resolve()) or path.exists():
        raise ValueError("output must be a new canonical file outside the checkout")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(row, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument(
        "--stage",
        required=True,
        choices=("source-head", "base-merge", "github-merge", "final-merge"),
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        row = build(ROOT, args.expected_sha, args.stage)
        write_output(args.output, row)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"FAIL_CHANNEL_MATRIX_SOURCE_PROVENANCE: {exc}\n")
    if not row["valid"]:
        for error in row["errors"]:
            print(f"FAIL_CHANNEL_MATRIX_SOURCE_PROVENANCE: {error}", file=sys.stderr)
        return 1
    print("PASS_CHANNEL_MATRIX_SOURCE_PROVENANCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
