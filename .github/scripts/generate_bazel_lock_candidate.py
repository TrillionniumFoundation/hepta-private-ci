#!/usr/bin/env python3
"""Retain one normal lock update and its complete tracked-input identities.

This requests dependency resolution, not build/test/run targets. Bazel module
extensions can still download and execute dependency tooling. Acceptance here
only establishes a generated lock candidate; it is not product qualification.
"""

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCK = "MODULE.bazel.lock"
COMMANDS = (
    ("before", ["./scripts/check-module-bazel-lock.sh"]),
    ("update", ["just", "bazel-lock-update"]),
    ("after", ["./scripts/check-module-bazel-lock.sh"]),
)


def git(*args):
    return subprocess.check_output(
        ["git", *args],
        cwd=ROOT,
        env={
            **os.environ,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_LAZY_FETCH": "1",
        },
    )


def identity(path):
    before = path.lstat()
    digest = hashlib.sha256()
    blob = hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0")
    size = 0
    if stat.S_ISREG(before.st_mode):
        kind = "file"
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                blob.update(chunk)
                size += len(chunk)
    elif stat.S_ISLNK(before.st_mode):
        kind = "symlink"
        data = os.fsencode(os.readlink(path))
        digest.update(data)
        blob.update(data)
        size = len(data)
    else:
        raise ValueError(f"unsupported tracked file type: {path}")
    after = path.lstat()
    stable = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    if size != before.st_size or any(
        getattr(before, key) != getattr(after, key) for key in stable
    ):
        raise ValueError(f"file changed while reading: {path}")
    return {
        "kind": kind,
        "mode": stat.S_IMODE(before.st_mode),
        "bytes": size,
        "sha256": digest.hexdigest(),
        "git_blob": blob.hexdigest(),
    }


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def snapshot():
    head = git("rev-parse", "HEAD").decode().strip()
    tree = git("rev-parse", "HEAD^{tree}").decode().strip()
    tree_entries = git("ls-tree", "-r", "-z", "--full-tree", "HEAD")
    index = git("ls-files", "--stage", "-z")
    committed = {}
    files = {}
    for record in tree_entries.split(b"\0"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        mode, kind, blob = header.decode().split()
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ValueError("unsupported Git tree entry")
        path = os.fsdecode(raw_path)
        committed[path] = [mode, blob, "0"]
        files[path] = {
            "git_mode": mode,
            "committed_blob": blob,
            **identity(ROOT / path),
        }
    indexed = {}
    for record in index.split(b"\0"):
        if record:
            header, raw_path = record.split(b"\t", 1)
            path = os.fsdecode(raw_path)
            if path in indexed:
                raise ValueError("multiple index stages for one path")
            indexed[path] = header.decode().split()
    return {
        "head": head,
        "tree": tree,
        "index_entries_sha256": hashlib.sha256(index).hexdigest(),
        "index_matches_head": indexed == committed,
        "files": files,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    if output.parent.resolve() != Path(os.environ["RUNNER_TEMP"]).resolve():
        raise ValueError("output must be a new directory directly under RUNNER_TEMP")
    output.mkdir()
    result = {
        "schema": "bazel-lock-candidate-v1",
        "candidate_accepted": False,
        "product_qualified": False,
        "expected_head": os.environ["EXPECTED_SHA"],
        "event_sha": os.environ["EVENT_SHA"],
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "commands": [],
        "errors": [],
    }
    before = None
    after = None
    try:
        before = snapshot()
        save(output / "inputs-before.json", before)
        result["checkout_before"] = {key: before[key] for key in ("head", "tree")}
        result["lock_before"] = before["files"].get(LOCK)
        if (
            before["head"] != result["expected_head"]
            or not before["index_matches_head"]
        ):
            raise ValueError("checkout/index does not match the requested candidate")
        for path, item in before["files"].items():
            mode = (
                "120000"
                if item["kind"] == "symlink"
                else ("100755" if item["mode"] & 0o111 else "100644")
            )
            if item["git_blob"] != item["committed_blob"] or mode != item["git_mode"]:
                raise ValueError(f"tracked input differs from checkout: {path}")
        if before["files"][LOCK]["kind"] != "file":
            raise ValueError("lock must be a regular tracked file")
        for name, argv in COMMANDS:
            row = {"name": name, "argv": argv, "exit_code": None}
            with (output / f"bazel-lock-{name}.log").open("xb") as log:
                try:
                    row["exit_code"] = subprocess.run(
                        argv,
                        cwd=ROOT,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=False,
                    ).returncode
                except OSError as error:
                    row["launch_error"] = f"{type(error).__name__}: {error}"
                    log.write((row["launch_error"] + "\n").encode())
            (output / f"bazel-lock-{name}.exit").write_text(
                str(row["exit_code"]) + "\n", encoding="utf-8"
            )
            result["commands"].append(row)
    except Exception as error:
        result["errors"].append(f"generation: {type(error).__name__}: {error}")
    finally:
        try:
            after = snapshot()
            save(output / "inputs-after.json", after)
            result["checkout_after"] = {key: after[key] for key in ("head", "tree")}
            result["lock_after"] = after["files"].get(LOCK)
            if before is None:
                raise ValueError("no complete admitted input snapshot")
            if any(
                before[key] != after[key]
                for key in (
                    "head",
                    "tree",
                    "index_entries_sha256",
                    "index_matches_head",
                )
            ):
                raise ValueError("HEAD, tree or index changed")
            paths = sorted(set(before["files"]) | set(after["files"]))
            changed = [
                p for p in paths if before["files"].get(p) != after["files"].get(p)
            ]
            result["changed_tracked_paths"] = changed
            if any(path != LOCK for path in changed):
                raise ValueError("tracked inputs other than MODULE.bazel.lock changed")
            old_lock, new_lock = before["files"][LOCK], after["files"][LOCK]
            if any(
                old_lock[key] != new_lock[key] for key in ("kind", "mode", "git_mode")
            ):
                raise ValueError("lock type or mode changed")
        except Exception as error:
            result["errors"].append(
                f"input verification: {type(error).__name__}: {error}"
            )
        try:
            diff = git(
                "diff",
                "--binary",
                "--full-index",
                "--no-ext-diff",
                "--no-textconv",
                "HEAD",
                "--",
                LOCK,
            )
            (output / "MODULE.bazel.lock.patch").write_bytes(diff)
            if after is None or after["files"][LOCK]["kind"] != "file":
                raise ValueError("no complete final lock identity")
            shutil.copyfile(ROOT / LOCK, output / LOCK)
            copied = identity(output / LOCK)
            if any(
                copied[key] != after["files"][LOCK][key]
                for key in ("bytes", "sha256", "git_blob")
            ):
                raise ValueError("exported lock differs from the final snapshot")
        except Exception as error:
            result["errors"].append(f"lock export: {type(error).__name__}: {error}")
        try:
            result["artifact_files"] = {
                path.name: identity(path) for path in sorted(output.iterdir())
            }
        except Exception as error:
            result["errors"].append(
                f"artifact identity: {type(error).__name__}: {error}"
            )
        codes = {row["name"]: row["exit_code"] for row in result["commands"]}
        result["candidate_accepted"] = (
            not result["errors"]
            and len(result["commands"]) == len(COMMANDS)
            and all(isinstance(row["exit_code"], int) for row in result["commands"])
            and codes.get("update") == 0
            and codes.get("after") == 0
        )
        save(output / "receipt.json", result)
    return 0 if result["candidate_accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())
