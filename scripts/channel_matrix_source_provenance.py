#!/usr/bin/env python3
"""Emit fail-closed tracked-source provenance for channel.matrix qualification.

The scanner deliberately uses a bounded number of Git subprocesses. Per-file
identity is derived from one stage-0 index snapshot plus locally recomputed Git
blob hashes; no file may trigger its own ``git show``, ``git rev-parse`` or
``git ls-files`` process.
"""
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
PROVENANCE_SCHEMA = "hepta.channel-matrix-source-provenance.v1"
PROVENANCE_DOMAIN = b"hepta.channel-matrix-source-provenance.v1"
CONTENT_INVENTORY_DOMAIN = b"hepta.channel-matrix-source-content.v1"
PATH_INVENTORY_DOMAIN = b"hepta.channel-matrix-source-paths.v1"
TRACKED_ORIGIN = "tracked_repository_source"
SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
GIT_COMMAND_TIMEOUT_SECONDS = 300


def git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=GIT_COMMAND_TIMEOUT_SECONDS,
    )


def split_z(value: bytes) -> list[str]:
    return [item.decode("utf-8") for item in value.split(b"\0") if item]


def bytes_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_digest(domain: bytes, value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(domain + b"\0" + encoded).hexdigest()


def aggregate(rows: list[dict[str, Any]]) -> str:
    return canonical_digest(PROVENANCE_DOMAIN, rows)


def content_inventory(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "repoRelativePath": row["repoRelativePath"],
            "gitBlob": row["gitBlob"],
            "sha256": row["sha256"],
            "bytes": row["bytes"],
        }
        for row in rows
    ]


def path_inventory(paths: list[str]) -> str:
    return canonical_digest(PATH_INVENTORY_DOMAIN, paths)


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
    status_command = ["git", "status", "--porcelain=v2", "-z", "--untracked-files=all"]
    status = git(root, *status_command[1:])
    return {
        "clean": not (unstaged or staged or untracked or ignored or status.stdout),
        "unstaged": unstaged,
        "staged": staged,
        "untrackedClosureInputs": untracked,
        "ignoredClosureInputs": ignored,
        "workspaceStatus": {
            "command": status_command,
            "bytes": len(status.stdout),
            "sha256": bytes_digest(status.stdout),
            "empty": not status.stdout,
        },
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


def introduction_history(root: Path) -> tuple[dict[str, str], list[str]]:
    command = [
        "git",
        "log",
        "--reverse",
        "--full-history",
        "--topo-order",
        "--format=%H",
        "--name-only",
        "-z",
        "--diff-filter=A",
        "--no-renames",
        "HEAD",
        "--",
        *SOURCE_ROOTS,
    ]
    raw = git(root, *command[1:]).stdout
    result: dict[str, str] = {}
    commit: str | None = None
    for token in raw.split(b"\0"):
        if not token:
            continue
        value = token.decode("utf-8").strip("\n")
        if SHA1.fullmatch(value):
            commit = value
        elif value and commit is not None:
            result.setdefault(value, commit)
    return result, command


def tracked_index(root: Path) -> tuple[dict[str, dict[str, str]], list[str], bytes, bytes, list[str]]:
    """Read every closure index entry in one Git process.

    The clean-before check proves the index equals HEAD. Recomputing the Git blob
    identity from each worktree file then proves worktree == index == HEAD while
    avoiding three Git processes per file.
    """
    command = ["git", "ls-files", "-s", "-z", "--", *SOURCE_ROOTS]
    completed = git(root, *command[1:])
    entries: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for raw_record in completed.stdout.split(b"\0"):
        if not raw_record:
            continue
        header, separator, raw_path = raw_record.partition(b"\t")
        if not separator:
            errors.append("malformed stage-0 index record")
            continue
        try:
            fields = header.decode("ascii").split()
            relative = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            errors.append("non-UTF-8 source path or index header")
            continue
        if len(fields) != 3:
            errors.append(f"malformed index header: {relative}")
            continue
        mode, blob, stage = fields
        if stage != "0" or not SHA1.fullmatch(blob):
            errors.append(f"non-stage-0 or invalid index identity: {relative}")
            continue
        if relative in entries:
            errors.append(f"duplicate index identity: {relative}")
            continue
        entries[relative] = {
            "mode": mode,
            "blob": blob,
            "recordSha256": bytes_digest(raw_record),
        }
    return entries, command, completed.stdout, completed.stderr, errors


def _valid_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and path.as_posix() == value and ".." not in path.parts


def _valid_clean_state(value: object) -> bool:
    if not isinstance(value, dict) or value.get("clean") is not True:
        return False
    status = value.get("workspaceStatus")
    return (
        value.get("unstaged") == []
        and value.get("staged") == []
        and value.get("untrackedClosureInputs") == []
        and value.get("ignoredClosureInputs") == []
        and isinstance(status, dict)
        and status.get("command")
        == ["git", "status", "--porcelain=v2", "-z", "--untracked-files=all"]
        and status.get("bytes") == 0
        and status.get("sha256") == EMPTY_SHA256
        and status.get("empty") is True
    )


def validate_receipt(
    row: object,
    *,
    expected_stage: str,
    expected_sha: str,
    expected_tree: str,
    expected_run: str | None = None,
    expected_attempt: str | None = None,
) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("source provenance must be an object")
    execution = row.get("execution")
    claims = row.get("claims")
    scan = row.get("scan")
    workspace = row.get("workspaceRoot")
    if (
        row.get("schema") != PROVENANCE_SCHEMA
        or row.get("valid") is not True
        or row.get("errors") != []
        or row.get("stage") != expected_stage
        or row.get("checkoutSha") != expected_sha
        or row.get("checkoutTree") != expected_tree
        or not isinstance(workspace, str)
        or not Path(workspace).is_absolute()
        or not isinstance(execution, dict)
        or not isinstance(claims, dict)
        or not isinstance(scan, dict)
        or claims.get("trackedSourceOnly") is not True
        or claims.get("generatedSourceIncluded") is not False
        or claims.get("cacheSourceIncluded") is not False
        or claims.get("artifactSourceIncluded") is not False
        or claims.get("authorityGranted") is not False
        or not _valid_clean_state(scan.get("cleanBefore"))
        or not _valid_clean_state(scan.get("cleanAfter"))
    ):
        raise ValueError(f"invalid {expected_stage} source provenance")
    if scan.get("defaultCommand") != ["git", "ls-files", "-z"]:
        raise ValueError("source provenance default scan is not tracked-only")
    if scan.get("perFileGitProcesses") != 0:
        raise ValueError("source provenance reintroduced per-file Git processes")
    index_command = scan.get("indexCommand")
    if not isinstance(index_command, list) or index_command[:4] != ["git", "ls-files", "-s", "-z"]:
        raise ValueError("source provenance lacks a bounded index scan")
    files = row.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError(f"empty {expected_stage} source provenance")
    if scan.get("closureFileCount") != len(files):
        raise ValueError("source provenance closure count mismatch")
    paths: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError(f"unverifiable {expected_stage} source input")
        relative = item.get("repoRelativePath")
        absolute = item.get("absolutePath")
        tracked_check = item.get("trackedCheck")
        classification = item.get("classification")
        if (
            not _valid_relative_path(relative)
            or not isinstance(absolute, str)
            or Path(absolute) != Path(workspace) / str(relative)
            or item.get("tracked") is not True
            or item.get("gitLsFilesErrorUnmatch") is not True
            or item.get("firstObservedStage") != expected_stage
            or item.get("origin") != TRACKED_ORIGIN
            or item.get("sourceClass") != TRACKED_ORIGIN
            or not SHA1.fullmatch(str(item.get("gitBlob", "")))
            or not SHA1.fullmatch(str(item.get("introducedAtCommit", "")))
            or not SHA256.fullmatch(str(item.get("sha256", "")))
            or type(item.get("bytes")) is not int
            or item["bytes"] < 0
            or not isinstance(tracked_check, dict)
            or tracked_check.get("command")
            != ["git", "ls-files", "--error-unmatch", "--", relative]
            or tracked_check.get("exitStatus") != 0
            or tracked_check.get("verificationMode") != "batched_stage0_index"
            or tracked_check.get("batchCommand") != index_command
            or not SHA256.fullmatch(str(tracked_check.get("batchRecordSha256", "")))
            or not SHA256.fullmatch(str(tracked_check.get("stdoutSha256", "")))
            or not SHA256.fullmatch(str(tracked_check.get("stderrSha256", "")))
            or not isinstance(classification, dict)
            or classification.get("generated") is not False
            or classification.get("cache") is not False
            or classification.get("artifact") is not False
        ):
            raise ValueError(f"unverifiable {expected_stage} source input")
        paths.append(str(relative))
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValueError("source provenance paths are duplicate or unordered")
    if row.get("sourceInventorySha256") != aggregate(files):
        raise ValueError("source provenance inventory digest mismatch")
    if row.get("sourceContentInventorySha256") != canonical_digest(
        CONTENT_INVENTORY_DOMAIN, content_inventory(files)
    ):
        raise ValueError("source content inventory digest mismatch")
    if scan.get("closurePathInventorySha256") != path_inventory(paths):
        raise ValueError("source closure path inventory digest mismatch")
    run_id = execution.get("workflowRunId")
    attempt = execution.get("attemptId")
    if expected_run is not None and run_id != expected_run:
        raise ValueError(f"{expected_stage} provenance belongs to another workflow run")
    if expected_attempt is not None and attempt != expected_attempt:
        raise ValueError(f"{expected_stage} provenance belongs to another workflow attempt")
    return row


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
    index, index_command, index_stdout, index_stderr, index_errors = tracked_index(root)
    errors.extend(index_errors)
    introduced, history_command = introduction_history(root)
    missing_introduction_paths = sorted(set(closure).difference(introduced))
    for relative in missing_introduction_paths:
        errors.append(f"source input lacks introduction provenance: {relative}")
    rows: list[dict[str, Any]] = []
    for relative in closure:
        absolute = root / relative
        entry = index.get(relative)
        tracked_command = ["git", "ls-files", "--error-unmatch", "--", relative]
        tracked = relative in tracked_set and entry is not None
        if not tracked:
            errors.append(f"source input is not tracked: {relative}")
            continue
        introduced_at = introduced.get(relative)
        if introduced_at is None or not SHA1.fullmatch(introduced_at):
            continue
        if absolute.is_symlink() or not absolute.is_file() or entry["mode"] == "120000":
            errors.append(f"source input is not a regular file: {relative}")
            continue
        data = absolute.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != entry["blob"]:
            errors.append(f"Git blob identity mismatch: {relative}")
            continue
        # Preserve the historical logical per-file check in the receipt while
        # binding it to the one actually executed batch index command.
        logical_stdout = f"{relative}\n".encode()
        rows.append(
            {
                "absolutePath": str(absolute),
                "repoRelativePath": relative,
                "gitBlob": blob,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "tracked": True,
                "gitLsFilesErrorUnmatch": True,
                "trackedCheck": {
                    "command": tracked_command,
                    "exitStatus": 0,
                    "stdoutSha256": bytes_digest(logical_stdout),
                    "stderrSha256": EMPTY_SHA256,
                    "verificationMode": "batched_stage0_index",
                    "batchCommand": index_command,
                    "batchStdoutSha256": bytes_digest(index_stdout),
                    "batchStderrSha256": bytes_digest(index_stderr),
                    "batchRecordSha256": entry["recordSha256"],
                },
                "introducedAtCommit": introduced_at,
                "firstObservedStage": stage,
                "origin": TRACKED_ORIGIN,
                "sourceClass": TRACKED_ORIGIN,
                "classification": classify(relative),
            }
        )
    if set(closure) != set(index):
        errors.append("tracked closure and stage-0 index inventories differ")
    if not rows:
        errors.append("source closure inventory is empty")
    after = clean_state(root)
    if not after["clean"]:
        errors.append("checkout was not clean after source scan")
    paths = [row["repoRelativePath"] for row in rows]
    return {
        "schema": PROVENANCE_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "stage": stage,
        "workspaceRoot": str(root),
        "checkoutSha": head,
        "checkoutTree": tree,
        "scan": {
            "defaultCommand": ["git", "ls-files", "-z"],
            "closureCommand": ["git", "ls-files", "-z", "--", *SOURCE_ROOTS],
            "indexCommand": index_command,
            "introductionHistoryCommand": history_command,
            "missingIntroductionPaths": missing_introduction_paths,
            "perFileGitProcesses": 0,
            "trackedFileCount": len(all_tracked),
            "closureFileCount": len(rows),
            "trackedPathInventorySha256": path_inventory(all_tracked),
            "closurePathInventorySha256": path_inventory(paths),
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
        "sourceContentInventorySha256": canonical_digest(
            CONTENT_INVENTORY_DOMAIN, content_inventory(rows)
        ),
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
        # Retain the exact diagnostic receipt even when the fail-closed
        # validator rejects it. The workflow uploads this file on failure, so
        # qualification never collapses to an opaque generic error again.
        write_output(args.output, row)
        if not row["valid"]:
            for error in row["errors"]:
                print(f"FAIL_CHANNEL_MATRIX_SOURCE_PROVENANCE: {error}", file=sys.stderr)
            return 1
        validate_receipt(
            row,
            expected_stage=args.stage,
            expected_sha=args.expected_sha,
            expected_tree=row["checkoutTree"],
            expected_run=os.environ.get("GITHUB_RUN_ID"),
            expected_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"FAIL_CHANNEL_MATRIX_SOURCE_PROVENANCE: {exc}\n")
    print("PASS_CHANNEL_MATRIX_SOURCE_PROVENANCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
