#!/usr/bin/env python3
"""Read-only exact-candidate and artifact binding for channel.matrix.

This records source/command provenance, not Matrix delivery, deployment or
independent acceptance. In particular, a focused Cargo/nextest run cannot
stand in for an authenticated Synapse qualification run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    "codex-rs/hepta-matrix-protocol",
    "codex-rs/hepta-matrix-store",
    "codex-rs/hepta-matrix-sdk",
    "codex-rs/hepta-matrixd",
    "docs/modules/channel.matrix",
    "scripts/verify_channel_matrix_candidate.py",
    "scripts/channel_matrix_evidence.py",
    "scripts/tests/test_channel_matrix_evidence.py",
    ".github/workflows/channel-matrix-preserve-unknown.yml",
    "codex-rs/Cargo.lock",
    "MODULE.bazel.lock",
)


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=60,
    ).stdout


def exact_commit(root: Path, value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("an exact 40-character commit SHA is required")
    if git(root, "rev-parse", f"{value}^{{commit}}").decode().strip() != value:
        raise ValueError("commit identity changed during resolution")
    return value


def clean(root: Path) -> None:
    # Tests must not mutate even an unrelated tracked contract/lockfile.
    git(root, "diff", "--exit-code", "HEAD", "--")
    git(root, "diff", "--cached", "--exit-code", "--")
    untracked = git(root, "ls-files", "--others", "-z", "--", *SOURCE_ROOTS)
    if untracked:
        raise ValueError("untracked (including ignored) Matrix source/evidence inputs exist")


def snapshot(
    root: Path, expected: str, source: str, base: str, lane: str,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    for value in (expected, source, base):
        exact_commit(root, value)
    head = git(root, "rev-parse", "HEAD").decode().strip()
    if head != expected:
        raise ValueError("checked-out HEAD differs from the expected candidate")
    if lane == "source-head":
        if head != source:
            raise ValueError("source-head lane is not testing the source commit")
    elif lane == "base-merge":
        parents = git(root, "rev-list", "--parents", "-n", "1", head).decode().split()[1:]
        if parents != [base, source]:
            raise ValueError("merge candidate does not have the exact base/source parents")
        merged_tree = git(root, "merge-tree", "--write-tree", base, source).decode().strip()
        if git(root, "rev-parse", "HEAD^{tree}").decode().strip() != merged_tree:
            raise ValueError("merge candidate tree differs from deterministic merge output")
    else:
        raise ValueError("unsupported candidate lane")
    clean(root)
    paths = git(root, "ls-files", "-z", "--", *SOURCE_ROOTS).split(b"\0")
    files: list[dict[str, Any]] = []
    for raw in paths:
        if not raw:
            continue
        relative = raw.decode("utf-8")
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"non-regular source file: {relative}")
        data = path.read_bytes()
        committed = git(root, "show", f"{head}:{relative}")
        if data != committed:
            raise ValueError(f"working bytes differ from committed bytes: {relative}")
        files.append({
            "path": relative,
            "gitBlob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })
    if not files:
        raise ValueError("candidate has no Matrix inputs")
    return {
        "schema": "hepta.channel-matrix-source-snapshot.v1",
        "lane": lane, "sourceSha": source, "baseSha": base, "testedSha": head,
        "testedTree": git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
        "files": files,
        "claims": {"sourceBytesBound": True, "testsPassed": False,
                   "homeserverQualified": False, "authorityGranted": False},
    }


def manifest(directory: Path, status: str) -> dict[str, Any]:
    if status not in ("success", "failure", "cancelled"):
        raise ValueError("missing or unsupported runner job status")
    directory = directory.resolve(strict=True)
    files = []
    for path in sorted(directory.rglob("*")):
        if path.name == "manifest.json":
            continue
        if path.is_symlink():
            raise ValueError("evidence contains a symlink")
        if not path.is_file():
            continue
        payload = path.read_bytes()
        files.append({"path": path.relative_to(directory).as_posix(), "bytes": len(payload),
                      "sha256": hashlib.sha256(payload).hexdigest()})
    if status == "success":
        required = {"source.json", "source-after.json", "candidate.json", "focused-tests.log", "clippy.log"}
        if not required.issubset({item["path"] for item in files if item["bytes"]}):
            raise ValueError("successful job is missing source/test/lint evidence")
        if (directory / "source.json").read_bytes() != (directory / "source-after.json").read_bytes():
            raise ValueError("source changed during qualification")
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema": "hepta.channel-matrix-artifact-manifest.v1",
        "runnerReportedStatus": status,
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "files": files,
        "artifactSetSha256": hashlib.sha256(b"hepta.matrix.artifacts.v1\0" + encoded).hexdigest(),
        "claims": {"homeserverQualified": False, "independentAcceptance": False,
                   "activation": False, "release": False, "authorityGranted": False},
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("snapshot")
    capture.add_argument("--expected-sha", required=True)
    capture.add_argument("--source-sha", required=True)
    capture.add_argument("--base-sha", required=True)
    capture.add_argument("--lane", required=True, choices=("source-head", "base-merge"))
    capture.add_argument("--output", type=Path, required=True)
    artifacts = commands.add_parser("manifest")
    artifacts.add_argument("--directory", type=Path, required=True)
    artifacts.add_argument("--job-status", required=True)
    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            value = snapshot(ROOT, args.expected_sha, args.source_sha, args.base_sha, args.lane)
            if args.output.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError("receipts must be outside the candidate checkout")
            write_json(args.output, value)
        else:
            write_json(args.directory / "manifest.json", manifest(args.directory, args.job_status))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"FAIL_CHANNEL_MATRIX_EVIDENCE: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
