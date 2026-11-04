#!/usr/bin/env python3
"""Archive existing log/XML records for console-selected failed Bazel targets."""

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


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


def collect(testlogs: Path, output: Path, targets: list[str]) -> tuple[Path, bool]:
    archive_root = output / "failed-test-logs"
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
                            manifest["files"].append(
                                {
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
    parser.add_argument("--testlogs-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    targets = list(
        dict.fromkeys(line.rstrip("\r\n") for line in sys.stdin if line.strip())
    )
    try:
        archive, complete = collect(args.testlogs_dir, args.output_dir, targets)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Failed-test-log archive could not be written: {error}", file=sys.stderr)
        return 1
    print(
        f"Failed-test-log archive: {archive} (complete_for_selected_targets={complete})"
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
