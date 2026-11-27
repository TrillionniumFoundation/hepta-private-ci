#!/usr/bin/env python3
"""Preserve materialized Bazel attempt logs without changing test outcomes."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
EVENT = re.compile(r"^(FAIL|TIMEOUT):\s+(\S+)(?:\s|$)")
SUMMARY = re.compile(
    r"^((?:@@?[^ /]+)?//\S+)\s+(?:\(cached\)\s+)?(FAILED|TIMEOUT|FLAKY)\b"
)
ACTION_ERROR = re.compile(r"^ERROR: .* Testing (\S+) failed:")
LOG_NAME = re.compile(r"^(?:test|attempt_[1-9][0-9]*)\.log$")
DATA_NAME = re.compile(r"^(?:test|attempt_[1-9][0-9]*)\.(?:log|xml)$")
CHILD_DIR = re.compile(r"^(?:test_attempts|(?:shard|run)_[1-9][0-9]*_of_[1-9][0-9]*)$")


def parse_console(console):
    events = []
    reported = []
    for number, raw in enumerate(console.splitlines(), 1):
        line = ANSI.sub("", raw).strip()
        event = EVENT.match(line)
        summary = SUMMARY.match(line)
        error = ACTION_ERROR.match(line)
        if event or summary or error:
            if event:
                status, label = event.groups()
            elif summary:
                label, status = summary.groups()
            else:
                label, status = error.group(1), "ACTION_ERROR"
            events.append(
                {"line": number, "label": label, "status": status, "text": line}
            )
        reference = re.search(r"\(see (.+\.log)\)$", line)
        if reference:
            reported.append({"line": number, "path": reference.group(1)})
        elif line.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", line):
            if LOG_NAME.fullmatch(line.replace("\\", "/").rsplit("/", 1)[-1]):
                reported.append({"line": number, "path": line})
    return events, reported


def checked_path(path, root):
    if ".." in path.parts:
        raise ValueError("parent traversal is not an attempt log path")
    source = path.absolute()
    relative = source.relative_to(root)
    current = root
    # The bazel-testlogs root itself may be Bazel's workspace symlink.
    # Require canonical-root paths and refuse symlinks beneath it. This is a
    # static check, not protection against replacement by a hostile host.
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink below the testlogs root")
    return source, relative


def copy_file(source, destination):
    """Copy the initial complete regular file, checking for concurrent changes."""
    result = {"source": str(source), "artifact": destination.name}
    digest = hashlib.sha256()
    copied = 0
    partial = destination.with_name(destination.name + ".partial")
    try:
        mode = source.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("source is not a regular file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(source, flags), "rb") as reader:
            before = os.fstat(reader.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("opened source is not a regular file")
            with partial.open("xb") as writer:
                remaining = before.st_size
                while remaining:
                    block = reader.read(min(1024 * 1024, remaining))
                    if not block:
                        raise OSError("source became shorter while reading")
                    writer.write(block)
                    digest.update(block)
                    copied += len(block)
                    remaining -= len(block)
                if reader.read(1):
                    raise OSError("source grew while reading")
            after = os.fstat(reader.fileno())
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise OSError("source changed while reading")
        partial.rename(destination)
        result.update(status="copied", bytes=copied, sha256=digest.hexdigest())
    except (OSError, ValueError) as error:
        result.update(status="unavailable", error=str(error))
        if partial.exists():
            result["partial_artifact"] = partial.name
            try:
                partial_digest = hashlib.sha256()
                partial_bytes = 0
                with partial.open("rb") as reader:
                    for block in iter(lambda: reader.read(1024 * 1024), b""):
                        partial_digest.update(block)
                        partial_bytes += len(block)
                result.update(
                    partial_bytes=partial_bytes,
                    partial_sha256=partial_digest.hexdigest(),
                )
            except OSError as partial_error:
                result["partial_identity_error"] = str(partial_error)
    return result


def target_directory(label, root):
    match = re.fullmatch(r"//([^:]*):(.+)", label)
    if not match:
        return None
    parts = (match.group(1) + "/" + match.group(2)).strip("/").split("/")
    if any(part in ("", ".", "..") or "\\" in part or ":" in part for part in parts):
        raise ValueError("invalid main-repository label path")
    return root.joinpath(*parts)


def discover_attempts(directory, root, paths, errors):
    try:
        directory, _ = checked_path(directory, root)
        for entry in sorted(directory.iterdir()):
            if DATA_NAME.fullmatch(entry.name):
                paths.add(entry.with_suffix(".log"))
            elif CHILD_DIR.fullmatch(entry.name):
                if entry.is_symlink():
                    raise ValueError(f"symlink attempt directory: {entry}")
                if entry.is_dir():
                    discover_attempts(entry, root, paths, errors)
    except (OSError, ValueError, RuntimeError) as error:
        errors.append({"source": str(directory), "error": str(error)})


def collect(args):
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="test-attempt-logs-", dir=output_root))
    files = output / "files"
    files.mkdir()
    console = copy_file(args.console_log, output / "console.log")
    events, reported = parse_console(
        (output / "console.log").read_text(errors="replace")
        if console["status"] == "copied"
        else ""
    )
    manifest = {
        "schema_version": 1,
        "bazel_exit_code": args.bazel_exit_code,
        "context": {
            name: os.environ.get(name)
            for name in (
                "GITHUB_SHA",
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_JOB",
                "RUNNER_OS",
            )
        },
        "console": console,
        "testlogs_root_requested": str(args.testlogs_root),
        "events": events,
        "targets": [],
        "reported_paths": reported,
        "attempts": [],
        "errors": [],
        "scope": (
            "Console-reported attempt paths and materialized log/XML files in "
            "observed failing, timed-out or flaky main-repository test targets. "
            "Discovered files alone do not establish an attempt outcome."
        ),
    }
    paths = set()
    try:
        root = args.testlogs_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("testlogs root is not a directory")
        manifest["testlogs_root_resolved"] = str(root)
        for reference in reported:
            path = Path(reference["path"].replace("\\", "/"))
            try:
                if not path.is_absolute():
                    raise ValueError("reported log path is not absolute")
                checked, relative = checked_path(path, root)
                reference["relative_path"] = str(relative)
                paths.add(checked)
            except (OSError, ValueError, RuntimeError) as error:
                reference["error"] = str(error)
                manifest["errors"].append(reference)
        for label in sorted({event["label"] for event in events}):
            try:
                directory = target_directory(label, root)
                if directory is not None:
                    discovered = set()
                    discover_attempts(directory, root, discovered, manifest["errors"])
                    paths.update(discovered)
                    manifest["targets"].append(
                        {
                            "label": label,
                            "discovered_attempts": len(discovered),
                            "relative_log_paths": sorted(
                                str(path.relative_to(root)) for path in discovered
                            ),
                        }
                    )
                    if not discovered:
                        raise ValueError(
                            "observed target has no materialized attempt files"
                        )
                else:
                    raise ValueError("external target discovery is not mapped")
            except ValueError as error:
                manifest["errors"].append({"label": label, "error": str(error)})
        for index, path in enumerate(sorted(paths), 1):
            attempt = {"relative_log_path": str(path.relative_to(root))}
            for role, source in (("log", path), ("junit", path.with_suffix(".xml"))):
                try:
                    source, _ = checked_path(source, root)
                    result = copy_file(source, files / f"{index:06d}{source.suffix}")
                    result["artifact"] = "files/" + result["artifact"]
                    if "partial_artifact" in result:
                        result["partial_artifact"] = (
                            "files/" + result["partial_artifact"]
                        )
                except (OSError, ValueError, RuntimeError) as error:
                    result = {
                        "source": str(source),
                        "status": "unavailable",
                        "error": str(error),
                    }
                attempt[role] = result
            manifest["attempts"].append(attempt)
    except (OSError, ValueError, RuntimeError) as error:
        manifest["errors"].append({"error": str(error)})
    manifest["complete_for_observed_scope"] = (
        not manifest["errors"]
        and console["status"] == "copied"
        and all(
            attempt[role]["status"] == "copied"
            for attempt in manifest["attempts"]
            for role in ("log", "junit")
        )
        and (not events or bool(manifest["attempts"]))
    )
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n")
    print(
        f"Bazel attempt evidence: {manifest_path}; "
        f"{len(manifest['attempts'])} log/XML pairs; "
        f"complete_for_observed_scope={manifest['complete_for_observed_scope']}"
    )
    return 0 if manifest["complete_for_observed_scope"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--console-log", type=Path, required=True)
    parser.add_argument("--testlogs-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--bazel-exit-code", type=int, required=True)
    return collect(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
