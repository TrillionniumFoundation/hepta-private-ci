#!/usr/bin/env python3
"""Build real sandbox test targets; verify their source/tool identity after tests."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

from windows_current_ci import git, source, valid_source

TARGETS = ("codex-command-runner", "codex-windows-sandbox-setup")


def files(paths):
    return {
        name: {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in paths.items()
    }


def check_after(expected, before, after, status, executables, tools):
    return (
        before.get("status") == "BUILT_REAL_TEST_HELPERS"
        and valid_source(expected, before["sourceBefore"], after)
        and not status
        and set(executables) == set(TARGETS)
        and before.get("executables") == executables
        and before.get("toolFiles") == tools
        and len(tools) == 3
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verify-after", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if (
        sys.platform != "win32"
        or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"
        or not re.fullmatch(r"[0-9a-f]{40}", args.expected_head)
        or output.is_relative_to(root)
    ):
        raise ValueError(
            "one actual native attempt with exact source and external receipts required"
        )
    for key in list(os.environ):
        if key.startswith("GIT_"):
            os.environ.pop(key)
    os.environ["GIT_NO_REPLACE_OBJECTS"] = "1"
    target = Path(os.environ["RUNNER_TEMP"]) / "hepta-windows-current-target"
    if Path(os.environ["CARGO_TARGET_DIR"]).resolve() != target.resolve():
        raise ValueError(
            "helper build and original tests must share their dedicated target"
        )
    executables = {name: target / "dev-small" / (name + ".exe") for name in TARGETS}
    tools = {
        name: Path(
            subprocess.check_output(
                ["rustup", "which", "--toolchain", "1.96.0", name], text=True
            ).strip()
        ).resolve(strict=True)
        for name in ("cargo", "rustc", "rustdoc")
    }
    observed = source(root)
    clean = git(root, "status", "--porcelain", "--untracked-files=all")
    if args.verify_after:
        result = {
            "schema": "hepta.windows-real-test-helpers-after.v1",
            "sourceAfter": observed,
            "sourceStatusAfter": clean,
            "functionalQualification": False,
            "passed": False,
        }
        try:
            before = json.loads((output / "build-receipt.json").read_text())
            result.update(
                executablesAfter=files(executables), toolFilesAfter=files(tools)
            )
            result["passed"] = check_after(
                args.expected_head,
                before,
                observed,
                clean,
                result["executablesAfter"],
                result["toolFilesAfter"],
            )
        except (OSError, ValueError, KeyError) as error:
            result["error"] = str(error)
        output.mkdir(parents=True, exist_ok=True)
        (output / "after-receipt.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
        return 0 if result["passed"] else 1
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": "hepta.windows-real-test-helpers-build.v1",
        "startedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "FAIL_REAL_TEST_HELPER_BUILD",
        "sourceBefore": observed,
        "sourceStatusBefore": clean,
        "platform": platform.platform(),
        "functionalQualification": False,
        "testScopeChanged": False,
    }
    try:
        if observed["head"] != args.expected_head or clean:
            raise ValueError("exact clean source required")
        compiler = subprocess.check_output(
            [str(tools["rustc"]), "--version", "--verbose"], text=True
        )
        cargo = subprocess.check_output([str(tools["cargo"]), "--version"], text=True)
        receipt.update(compiler=compiler, cargo=cargo, toolFiles=files(tools))
        if not (
            compiler.startswith("rustc 1.96.0 ")
            and "host: x86_64-pc-windows-msvc" in compiler
            and cargo.startswith("cargo 1.96.0 ")
        ):
            raise ValueError("native compiler pin differs")
        command = [
            str(tools["cargo"]),
            "build",
            "--locked",
            "-p",
            "codex-windows-sandbox",
            "--bins",
            "--profile",
            "dev-small",
        ]
        environment = dict(
            os.environ, RUSTC=str(tools["rustc"]), RUSTDOC=str(tools["rustdoc"])
        )
        started = time.monotonic()
        with (output / "build.log").open("x", encoding="utf-8") as stream:
            process = subprocess.run(
                command,
                cwd=root / "codex-rs",
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        receipt.update(
            command=command,
            exitCode=process.returncode,
            durationSeconds=round(time.monotonic() - started, 3),
        )
        if process.returncode:
            raise ValueError("actual sandbox helper target build failed")
        receipt["executables"] = files(executables)
        if set(receipt["executables"]) != set(TARGETS):
            raise ValueError("a real helper target is missing")
        after = source(root)
        status = git(root, "status", "--porcelain", "--untracked-files=all")
        if not (
            valid_source(args.expected_head, observed, after)
            and not status
            and receipt["toolFiles"] == files(tools)
        ):
            raise ValueError("source/compiler changed during real helper build")
        # Test-only resolver inputs reference the two actual just-built targets.
        # No ordinary PATH program or replacement fake executable is installed.
        rows = [
            f"CARGO_BIN_EXE_{name}={path.resolve(strict=True)}"
            for name, path in executables.items()
        ]
        if any("\n" in row or "\r" in row for row in rows):
            raise ValueError("test executable environment contains a line break")
        with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as stream:
            stream.write("\n".join(rows) + "\n")
        receipt["status"] = "BUILT_REAL_TEST_HELPERS"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        receipt["error"] = str(error)
    finally:
        try:
            receipt.update(
                sourceAfter=source(root),
                sourceStatusAfter=git(
                    root, "status", "--porcelain", "--untracked-files=all"
                ),
                toolFilesAfter=files(tools),
            )
            if not (
                valid_source(args.expected_head, observed, receipt["sourceAfter"])
                and not receipt["sourceStatusAfter"]
                and receipt.get("toolFiles") == receipt["toolFilesAfter"]
            ):
                receipt["status"] = "FAIL_REAL_TEST_HELPER_BUILD"
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            receipt.update(
                afterObservationError=str(error), status="FAIL_REAL_TEST_HELPER_BUILD"
            )
    receipt["finishedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (output / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"] == "BUILT_REAL_TEST_HELPERS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
