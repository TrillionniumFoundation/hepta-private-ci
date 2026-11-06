#!/usr/bin/env python3
"""Archive existing log/XML records for explicitly scoped Bazel console targets."""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


# A deliberately small acceptance-evidence scope, not an extra test selection.
RETAINED_TARGETS = (
    "//codex-rs/tui:tui-unit-tests",
    "//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests",
    "//codex-rs/ext/queue:queue-queue_service-test",
    "//codex-rs/app-server:app-server-all-test",
    "//codex-rs/app-server:app-server-unit-tests",
    "//codex-rs/app-server:app-server-all-wine-exec-test",
    "//codex-rs/codex-mcp:codex-mcp-unit-tests",
    "//codex-rs/core:core-unit-tests",
    "//codex-rs/core:core-all-test",
    "//codex-rs/core:core-all-wine-exec-test",
    "//codex-rs/hepta-agentd:hepta-agentd-cognitive-write-qualification-test",
    "//codex-rs/windows-sandbox-rs:codex-windows-sandbox-setup-bin-unit-tests",
    "//codex-rs/utils/pty:pty-unit-tests",
)


def retention_plan(console: Path) -> dict:
    data = console.read_bytes()
    reports = {target: [] for target in RETAINED_TARGETS}
    pattern = re.compile(
        r"^(//\S+)\s+(?:(\(cached\))\s+)?"
        r"(PASSED|FLAKY|FAILED|SKIPPED|TIMEOUT|NO STATUS)\b"
    )
    for original in data.decode("utf-8", errors="replace").splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", original).strip()
        match = pattern.match(line)
        if match and match[1] in reports:
            reports[match[1]].append(
                {
                    "status": match[3],
                    "cached_marker": match[2] is not None,
                    "summary_line": line,
                }
            )
    targets = {}
    errors = []
    for target, entries in reports.items():
        outcomes = {(entry["status"], entry["cached_marker"]) for entry in entries}
        status, cached = next(iter(outcomes)) if len(outcomes) == 1 else (None, None)
        if len(outcomes) > 1:
            errors.append(
                {
                    "target": target,
                    "path": "console summary",
                    "error": "Conflicting summaries; existing logs were not selected",
                }
            )
        targets[target] = {
            "status": status or ("AMBIGUOUS" if entries else "NOT_REPORTED"),
            "cached_marker": cached,
            "summary_lines": [entry["summary_line"] for entry in entries],
            "collect_existing_logs": status in ("PASSED", "FLAKY"),
        }
    return {
        "console_sha256": hashlib.sha256(data).hexdigest(),
        "console_bytes": len(data),
        "targets": targets,
        "selection_errors": errors,
        "limitations": (
            "NOT_REPORTED does not mean filtered or skipped. An absent cached marker "
            "does not prove local execution or an independent remote execution. "
            "Files are existing local records for a console-reported target; their "
            "binding to this invocation is not independently established. "
            "Bazel config expansion and per-case filtering must be checked separately. "
            "Checkout identity is recorded at collection time, not at test start."
        ),
    }


def target_path(label: str) -> Path:
    if not label.startswith("//") or "\\" in label:
        raise ValueError("expected a canonical //package:target label")
    package, separator, name = label[2:].partition(":")
    parts = (package.split("/") if package else []) + name.split("/")
    if not separator or any(
        part in ("", ".", "..")
        or ":" in part
        or any(ord(character) < 32 or ord(character) == 127 for character in part)
        for part in parts
    ):
        raise ValueError("unsafe or non-canonical target path")
    return Path(*parts)


def collect(
    testlogs: Path, output: Path, targets: list[str], *, retention: dict | None = None
) -> tuple[Path, bool]:
    archive_root = output / (
        "selected-target-test-logs" if retention is not None else "failed-test-logs"
    )
    archive_root.mkdir(parents=True, exist_ok=True)
    archive = Path(tempfile.mkdtemp(prefix="invocation-", dir=archive_root))
    manifest = {
        "schema": "bazel_failed_test_logs_v1",
        "scope": (
            "Existing test.log/test.xml and test_attempts log/XML files under "
            "console-selected failed targets only; not a complete suite inventory."
        ),
        "selected_targets": targets,
        "source": {},
        "files": [],
        "errors": [],
    }

    if retention is not None:
        manifest.update(
            schema="bazel_selected_target_logs_v1",
            scope=(
                "Existing local test.log/test.xml and test_attempts log/XML records "
                "for the allowlisted targets reported PASSED or FLAKY in this console; "
                "not failed-target-only evidence or a complete case/attempt inventory."
            ),
            retention=retention,
            complete_case_inventory=False,
        )
        manifest["errors"].extend(retention["selection_errors"])

    def record_error(target: str | None, path: str, error: Exception) -> None:
        manifest["errors"].append(
            {
                "target": target,
                "path": path,
                "error": f"{type(error).__name__}: {error}",
            }
        )

    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD", "HEAD^{tree}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.splitlines()
        dirty = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--"],
            check=False,
            capture_output=True,
            timeout=10,
        )
        if len(revision) != 2 or dirty.returncode not in (0, 1):
            raise ValueError("could not identify the checked-out Git source")
        manifest["source"] = {
            "commit": revision[0],
            "tree": revision[1],
            "tracked_worktree_dirty": dirty.returncode == 1,
        }
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        record_error(None, "git source", error)

    # Bazel's top-level bazel-testlogs entry may itself be a symlink.
    try:
        root = testlogs.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("testlogs root is not a directory")
    except (OSError, ValueError, RuntimeError) as error:
        record_error(None, "testlogs root", error)
        root = None

    if root is not None:
        for index, target in enumerate(targets):
            previous_count = len(manifest["files"])
            try:
                relative_target = target_path(target)
                directory = root / relative_target
                resolved = directory.resolve(strict=True)
                if not resolved.is_relative_to(root):
                    raise ValueError("target directory escapes the testlogs root")
                if not resolved.is_dir():
                    raise ValueError("target path is not a directory")

                def walk_error(error: OSError) -> None:
                    record_error(target, str(relative_target), error)

                for current, directories, filenames in os.walk(
                    directory, followlinks=False, onerror=walk_error
                ):
                    directories.sort()
                    current_path = Path(current)
                    for name in list(directories):
                        child = current_path / name
                        relative = child.relative_to(root)
                        if name in (
                            "test.outputs",
                            "test.outputs_manifest",
                        ) or name.endswith(".runfiles"):
                            directories.remove(name)
                            continue
                        try:
                            if not child.resolve(strict=True).is_relative_to(root):
                                raise ValueError("directory escapes the testlogs root")
                            if child.is_symlink() or getattr(
                                child.lstat(), "st_reparse_tag", 0
                            ):
                                raise ValueError(
                                    "nested linked directory is not traversed"
                                )
                        except (OSError, ValueError, RuntimeError) as error:
                            directories.remove(name)
                            record_error(target, relative.as_posix(), error)

                    for name in sorted(filenames):
                        source = current_path / name
                        target_relative = source.relative_to(directory)
                        if name not in ("test.log", "test.xml") and not (
                            "test_attempts" in target_relative.parts
                            and source.suffix in (".log", ".xml")
                        ):
                            continue
                        relative = source.relative_to(root)
                        destination = (
                            archive / "targets" / f"{index:04d}" / target_relative
                        )
                        try:
                            resolved = source.resolve(strict=True)
                            if not resolved.is_relative_to(root):
                                raise ValueError("file escapes the testlogs root")
                            if not stat.S_ISREG(resolved.stat().st_mode):
                                raise ValueError("log is not a regular file")
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            digest = hashlib.sha256()
                            size = 0
                            with (
                                resolved.open("rb") as reader,
                                destination.open("xb") as writer,
                            ):
                                before = os.fstat(reader.fileno())
                                while chunk := reader.read(1024 * 1024):
                                    writer.write(chunk)
                                    digest.update(chunk)
                                    size += len(chunk)
                                after = os.fstat(reader.fileno())
                            if (
                                size != before.st_size
                                or before.st_size != after.st_size
                                or before.st_mtime_ns != after.st_mtime_ns
                            ):
                                raise ValueError(
                                    "source log changed while being archived"
                                )
                            provenance = (
                                {"source_mtime_ns": before.st_mtime_ns}
                                if retention is not None
                                else {}
                            )
                            manifest["files"].append(
                                {
                                    **provenance,
                                    "target": target,
                                    "testlogs_relative_path": relative.as_posix(),
                                    "archive_relative_path": destination.relative_to(
                                        archive
                                    ).as_posix(),
                                    "bytes": size,
                                    "sha256": digest.hexdigest(),
                                }
                            )
                        except (OSError, ValueError, RuntimeError) as error:
                            try:
                                destination.unlink(missing_ok=True)
                            except OSError as cleanup_error:
                                record_error(target, relative.as_posix(), cleanup_error)
                            record_error(target, relative.as_posix(), error)
                if len(manifest["files"]) == previous_count:
                    raise ValueError(
                        "no existing test log/XML records found for target"
                    )
            except (OSError, ValueError, RuntimeError) as error:
                record_error(target, target, error)

    manifest["complete_for_selected_targets"] = not manifest["errors"]
    (archive / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return archive, manifest["complete_for_selected_targets"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--testlogs-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--retention-console", type=Path)
    parser.add_argument("--list-retention-targets", action="store_true")
    parser.add_argument("--invocation-args-file", type=Path)
    args = parser.parse_args()
    if args.list_retention_targets and args.retention_console is None:
        parser.error("--list-retention-targets requires --retention-console")
    if not args.list_retention_targets and (
        args.testlogs_dir is None or args.output_dir is None
    ):
        parser.error("--testlogs-dir and --output-dir are required for collection")
    archive_kind = "Selected-target" if args.retention_console else "Failed-test"
    try:
        retention = (
            retention_plan(args.retention_console) if args.retention_console else None
        )
        if args.list_retention_targets:
            for target, report in retention["targets"].items():
                if report["summary_lines"]:
                    print(target)
            return 0
        if retention is None:
            targets = list(
                dict.fromkeys(line.rstrip("\r\n") for line in sys.stdin if line.strip())
            )
        else:
            targets = [
                target
                for target, report in retention["targets"].items()
                if report["collect_existing_logs"]
            ]
            if args.invocation_args_file is not None:
                arguments = (
                    args.invocation_args_file.read_bytes().decode("utf-8").split("\0")
                )
                selection_options = {
                    "--config",
                    "--test_filter",
                    "--test_tag_filters",
                    "--build_tag_filters",
                    "--test_lang_filters",
                    "--test_size_filters",
                    "--test_timeout_filters",
                    "--test_timeout",
                    "--test_sharding_strategy",
                    "--runs_per_test",
                    "--flaky_test_attempts",
                    "--cache_test_results",
                    "--nocache_test_results",
                }
                requested = []
                take_next = False
                for argument in arguments:
                    if argument == "--":
                        break
                    if take_next:
                        requested.append(argument)
                        take_next = False
                    elif argument.split("=", 1)[0] in selection_options:
                        requested.append(argument)
                        take_next = "=" not in argument and argument not in (
                            "--cache_test_results",
                            "--nocache_test_results",
                        )
                retention["wrapper_requested_selection_flags"] = requested
        archive, complete = collect(
            args.testlogs_dir, args.output_dir, targets, retention=retention
        )
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(
            f"{archive_kind}-log archive could not be written: {error}", file=sys.stderr
        )
        return 1
    print(
        f"{archive_kind}-log archive: {archive} (complete_for_selected_targets={complete})"
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
