#!/usr/bin/env python3
"""Retain the existing job's lock bytes; never generate or validate a lock."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

LOCK = "MODULE.bazel.lock"
MAX_FILE = 8 * 1024 * 1024
MAX_GIT = 16 * 1024 * 1024
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_INPUTS = 4096
DIFF = [
    "diff",
    "--binary",
    "--full-index",
    "--no-ext-diff",
    "--no-textconv",
    "--no-renames",
    "--submodule=short",
    "--ignore-submodules=none",
]
STATUS = [
    "status",
    "--porcelain=v1",
    "-z",
    "--untracked-files=all",
    "--ignore-submodules=none",
]


class CaptureError(Exception):
    pass


def digest(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def plain(path, directory=False):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise CaptureError("symlink_or_reparse_point")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise CaptureError("not_a_regular_file_or_directory")
    return info


def source_bytes(root, name):
    path = root / name
    if not path.resolve().is_relative_to(root):
        raise CaptureError("source_escapes_checkout")
    for parent in path.parents:
        if parent == root:
            break
        plain(parent, directory=True)
    before = plain(path)
    if before.st_size > MAX_FILE:
        raise CaptureError("source_file_byte_limit")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as source:
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise CaptureError("opened_source_not_regular")
        data = source.read(MAX_FILE + 1)
        after = os.fstat(source.fileno())

    def signature(value):
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    if len(data) > MAX_FILE or any(
        signature(value) != signature(before) for value in (opened, after, plain(path))
    ):
        raise CaptureError("source_changed_during_read")
    return data


def git(root, output, *args):
    # Ordinary read-only Git commands, no shell, retry, timeout or subprocess
    # controller. Temporary streams stay in the existing artifact directory;
    # accepted output/read sizes are capped after Git exits, never truncated.
    with (
        tempfile.TemporaryFile(dir=output) as stdout,
        tempfile.TemporaryFile(dir=output) as stderr,
    ):
        result = subprocess.run(
            [
                "git",
                "--no-pager",
                "--no-optional-locks",
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(root),
                *args,
            ],
            stdout=stdout,
            stderr=stderr,
            check=False,
        )
        if result.returncode:
            raise CaptureError("git_read_failed")
        if stdout.tell() > MAX_GIT or stderr.tell() > MAX_GIT:
            raise CaptureError("git_output_byte_limit")
        stdout.seek(0)
        return stdout.read(MAX_GIT + 1)


def write(output, name, data):
    with (output / name).open("xb") as destination:
        destination.write(data)


def input_hashes(root, inventory):
    values = {}
    total = 0
    for record in inventory.split(b"\0"):
        if not record:
            continue
        metadata, raw_name = record.split(b"\t", 1)
        mode, kind, blob = metadata.decode("ascii").split()
        name = os.fsdecode(raw_name)
        path = Path(name)
        if name == LOCK or not (
            path.name
            in {
                "Cargo.toml",
                "Cargo.lock",
                "MODULE.bazel",
                ".bazelrc",
                ".bazelversion",
                "rust-toolchain.toml",
                "BUILD",
                "WORKSPACE",
            }
            or path.suffix in {".bazel", ".bzl"}
            or name.endswith(".cargo/config.toml")
        ):
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise CaptureError("input_is_not_regular_git_blob")
        data = source_bytes(root, name)
        total += len(data)
        if total > MAX_INPUT_BYTES or len(values) >= MAX_INPUTS:
            raise CaptureError("input_inventory_limit")
        values[name] = {"head_blob": blob, **digest(data)}
    required = {
        "MODULE.bazel",
        ".bazelrc",
        ".bazelversion",
        "codex-rs/Cargo.toml",
        "codex-rs/Cargo.lock",
    }
    if not required.issubset(values):
        raise CaptureError("required_input_missing")
    return values


def capture(root, runner_temp, build_outcome, prior_status):
    root = root.resolve(strict=True)
    runner_temp = runner_temp.resolve(strict=True)
    output = runner_temp / "bazel-execution-logs"
    if output.is_relative_to(root):
        raise CaptureError("artifact_directory_inside_checkout")
    output.mkdir(exist_ok=True)
    plain(output, directory=True)
    output = output / "module-lock-evidence"
    output.mkdir()  # Never overwrite/reuse a prior capture or follow its links.
    manifest = {
        "schema_version": 1,
        "classification": "UNVERIFIED",
        "candidate_kind": (
            "successful_build_candidate"
            if build_outcome == "success" and prior_status == "success"
            else "partial_failed_or_skipped_build_candidate"
        ),
        "build_step_outcome": build_outcome,
        "job_status_before_capture": prior_status,
        "lock_validation": "NOT_PERFORMED",
        "generator_provenance": "Observed after existing job steps; not established by capture",
        "capture_status": "FAILED",
        "files": {},
    }
    try:
        identity = git(root, output, "rev-parse", "HEAD", "HEAD^{tree}")
        head, tree = identity.decode("ascii").splitlines()
        manifest.update(head=head, tree=tree)
        inventory = git(root, output, "ls-tree", "-r", "-z", head)
        lock_entry = [
            entry
            for entry in inventory.split(b"\0")
            if entry.endswith(b"\t" + LOCK.encode())
        ]
        if len(lock_entry) != 1 or not lock_entry[0].startswith(
            (b"100644 blob ", b"100755 blob ")
        ):
            raise CaptureError("baseline_lock_not_regular_git_blob")
        manifest["baseline_lock_blob"] = (
            lock_entry[0].split(b"\t")[0].split()[2].decode("ascii")
        )
        current = source_bytes(root, LOCK)
        baseline = git(root, output, "show", f"{head}:{LOCK}")
        if len(baseline) > MAX_FILE:
            raise CaptureError("baseline_lock_byte_limit")
        for name, data in [
            ("MODULE.bazel.lock.current", current),
            ("MODULE.bazel.lock.HEAD", baseline),
        ]:
            write(output, name, data)
            manifest["files"][name] = digest(data)
        manifest["lock_bytes_differ_from_HEAD_blob"] = current != baseline
        names = [
            "diff",
            "--name-only",
            "-z",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--ignore-submodules=none",
        ]
        drift_commands = {
            "git-drift-HEAD-names.z": [*names, head, "--"],
            "git-drift-index-names.z": [*names, "--cached", head, "--"],
            "git-drift-worktree-names.z": [*names, "--"],
        }
        commands = {
            "git-status.porcelain-v1.z": STATUS,
            "git-diff-HEAD.patch": [*DIFF, head, "--", LOCK],
            "git-diff-index.patch": [*DIFF, "--cached", head, "--", LOCK],
            "git-diff-worktree.patch": [*DIFF, "--", LOCK],
            "git-tree.z": ["ls-tree", "-r", "-z", head],
            **drift_commands,
        }
        captured = {}
        for name, command in commands.items():
            data = git(root, output, *command)
            write(output, name, data)
            manifest["files"][name] = digest(data)
            captured[name] = data
        inputs = input_hashes(root, inventory)
        manifest["inputs"] = inputs
        # Check index and worktree independently: a staged non-lock change can
        # cancel out in the net HEAD diff. Retain only global names/status/tree,
        # never unrelated modified contents in the lock's binary patches.
        drift = any(
            name and name != LOCK.encode()
            for artifact in drift_commands
            for name in captured[artifact].split(b"\0")
        )
        manifest["tracked_source_drift"] = drift
        manifest["untracked_paths_present"] = any(
            record.startswith(b"?? ")
            for record in captured["git-status.porcelain-v1.z"].split(b"\0")
        )
        if identity != git(root, output, "rev-parse", "HEAD", "HEAD^{tree}"):
            raise CaptureError("head_changed_during_capture")
        if current != source_bytes(root, LOCK) or inputs != input_hashes(
            root, inventory
        ):
            raise CaptureError("inputs_changed_during_capture")
        for name, command in commands.items():
            if captured[name] != git(root, output, *command):
                raise CaptureError("git_state_changed_during_capture")
        if drift or manifest["untracked_paths_present"]:
            raise CaptureError("source_drift")
        manifest["capture_status"] = "COMPLETE"
    except (CaptureError, OSError, ValueError) as error:
        manifest["error"] = (
            str(error) if isinstance(error, CaptureError) else type(error).__name__
        )
    write(
        output,
        "manifest.json",
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
    )
    return 0 if manifest["capture_status"] == "COMPLETE" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build-outcome",
        required=True,
        choices=["success", "failure", "skipped", "cancelled"],
    )
    parser.add_argument(
        "--prior-status", required=True, choices=["success", "failure", "cancelled"]
    )
    args = parser.parse_args()
    try:
        return capture(
            Path(os.environ["GITHUB_WORKSPACE"]),
            Path(os.environ["RUNNER_TEMP"]),
            args.build_outcome,
            args.prior_status,
        )
    except (CaptureError, OSError, KeyError):
        print(
            "Module lock evidence capture failed before manifest completion.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
