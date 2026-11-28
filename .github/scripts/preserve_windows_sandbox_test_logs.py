#!/usr/bin/env python3
"""Retain complete logs from the three original Windows consumer targets."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

TARGETS = (
    "codex-rs/cli/cli-sandbox_cloud_config-test",
    "codex-rs/exec-server/exec-server-file_system_windows-test",
    "codex-rs/core/core-all-test",
)


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    destination = Path(os.environ["RUNNER_TEMP"]) / "windows-sandbox-complete-test-logs"
    destination.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable,
        str(root / ".github/scripts/run_bazel_with_buildbuddy.py"),
        "--noexperimental_remote_repo_contents_cache",
        "info",
        "--config=ci-windows",
        "--host_platform=//:local_windows_msvc",
        "--platforms=//:windows_x86_64_msvc",
        "bazel-testlogs",
    ]
    result = subprocess.run(command, cwd=root, capture_output=True, check=False)
    (destination / "bazel-info.stdout").write_bytes(result.stdout)
    (destination / "bazel-info.stderr").write_bytes(result.stderr)
    report: dict[str, object] = {
        "command": command,
        "returncode": result.returncode,
        "targets": list(TARGETS),
        "members": [],
        "status": "FAIL",
    }
    try:
        if result.returncode != 0:
            raise RuntimeError("cannot locate the original Bazel test-log root")
        lines = result.stdout.decode("utf-8", "strict").strip().splitlines()
        if len(lines) != 1:
            raise ValueError("Bazel returned an ambiguous test-log root")
        testlogs = Path(lines[0]).resolve(strict=True)
        report["testlogs"] = str(testlogs)
        if not testlogs.is_dir():
            raise ValueError("Bazel test-log root is not a directory")
        members = []
        for target in TARGETS:
            source = (testlogs / target).resolve(strict=True)
            source.relative_to(testlogs)
            if not source.is_dir():
                raise ValueError(f"missing original target log directory: {target}")
            found = 0
            for path in sorted(source.rglob("*")):
                if path.suffix not in {".log", ".xml"} or not path.is_file():
                    continue
                path.resolve(strict=True).relative_to(testlogs)
                relative = path.relative_to(testlogs).as_posix()
                before = path.stat()
                data = path.read_bytes()
                after = path.stat()
                if (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                ) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise ValueError(f"original log changed during capture: {relative}")
                output = destination / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("xb") as stream:
                    stream.write(data)
                digest = hashlib.sha256(data).hexdigest()
                if hashlib.sha256(output.read_bytes()).hexdigest() != digest:
                    raise ValueError(f"copied log differs: {relative}")
                members.append({"path": relative, "bytes": len(data), "sha256": digest})
                found += 1
            if found == 0:
                raise ValueError(f"no complete logs were retained for {target}")
        report["members"] = members
        report["status"] = "PASS"
        print(f"Preserved {len(members)} complete original target and attempt logs.")
    except BaseException as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        (destination / "capture.json").write_text(
            json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
