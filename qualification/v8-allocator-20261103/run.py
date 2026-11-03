#!/usr/bin/env python3
"""Qualify the original V8 consumers with exact hosted input and output evidence."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET


REPO = Path(__file__).resolve().parents[2]
PACKAGES = ["v8-poc", "code-mode-runtime", "code-mode-host"]
TARGETS = [f"//codex-rs/{name}:{name}-unit-tests" for name in PACKAGES]
REGRESSION = "tests::parallel_first_isolates_keep_array_buffers_independent"


def snapshot():
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "codex-rs/v8-poc", "codex-rs/code-mode-runtime",
         "codex-rs/code-mode-host", "codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
         "codex-rs/rust-toolchain.toml", "MODULE.bazel", "MODULE.bazel.lock", "defs.bzl",
         "workspace_root_test_launcher.*", ".bazelrc", ".bazelversion", "third_party/v8",
         "patches", "bazel/rules/testing", ".github/actions/prepare-bazel-ci",
         ".github/actions/setup-ci", ".github/actions/setup-bazel-ci",
         ".github/scripts/run_bazel_with_buildbuddy.py", ".github/scripts/run-bazel-ci.sh",
         ".github/scripts/run-bazel-query-ci.sh", "scripts/check-module-bazel-lock.sh",
         "scripts/list-bazel-clippy-targets.sh", "qualification/v8-allocator-20261103",
         ".github/workflows/hepta-v8-allocator-qualification.yml"], cwd=REPO,
    ).decode().split("\0")
    return {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in paths if name}


def copy_test_result(output, name, prefix, testlogs):
    source = testlogs / "codex-rs" / name / f"{name}-unit-tests"
    for suffix in ["log", "xml"]:
        shutil.copyfile(source / f"test.{suffix}", output / f"{prefix}.{suffix}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", choices=["ci-windows", "ci-linux"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    (output / "source-inputs.json").write_text(json.dumps(before, indent=2) + "\n")
    receipt = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
               "status": "failed", "platform": platform.platform(), "machine": platform.machine(),
               "config": args.config, "steps": []}
    wrapper = "./.github/scripts/run_bazel_with_buildbuddy.py"
    config = f"--config={args.config}"
    windows = args.config == "ci-windows"
    # Use the exact shell that runs this workflow. On Windows, an unqualified
    # Python subprocess "bash" can resolve to the unrelated system WSL launcher.
    bash = Path(os.environ["V8_QUALIFICATION_BASH"]).resolve(strict=True)
    if not bash.is_file():
        raise RuntimeError("the workflow's Bash executable is not a file")
    receipt["bash_executable"] = str(bash)
    platform_flags = ["--platforms=//:windows_x86_64_msvc"] if windows else []
    host_flags = ["--host_platform=//:local_windows_msvc"] if windows else []
    # The CI default downloads minimal remote outputs. Materialize complete
    # top-level test outputs, including test.xml, before retaining evidence.
    wrapper_flags = (["--windows-msvc-host-platform"] if windows else []) + ["--remote-download-toplevel"]
    original_wrapper = [str(bash), "./.github/scripts/run-bazel-ci.sh", "--print-failed-test-logs",
                        "--print-failed-action-summary", *wrapper_flags, "--"]
    # The original workflow checks the universal lock on Linux, and uses its
    # complete native MSVC wrapper/environment on Windows.
    commands = [] if windows else [("committed-lock-check", [str(bash), "./scripts/check-module-bazel-lock.sh"])]
    commands.extend([
        ("fresh-parallel-first-use", [*original_wrapper, "test", *platform_flags, "--nocache_test_results",
                                      "--test_output=all", f"--test_arg={REGRESSION}", "--test_arg=--exact", "--", TARGETS[0]]),
        ("original-consumer-tests", [*original_wrapper, "test", *platform_flags, "--nocache_test_results", "--test_output=all", "--", *TARGETS]),
        ("original-clippy-selector", [str(bash), "./scripts/list-bazel-clippy-targets.sh"]),
        ("original-consumer-clippy", [*original_wrapper, "build", *platform_flags, "--config=clippy", "--", *[name + "-bin" for name in TARGETS]]),
    ])
    testlogs = None
    try:
        if windows != (platform.system() == "Windows"):
            raise RuntimeError("qualification platform does not match the requested native configuration")
        if not os.environ.get("BUILDBUDDY_API_KEY"):
            raise RuntimeError("qualification requires original authenticated RBE")
        for name, command in commands:
            start = time.monotonic()
            with (output / f"{name}.stdout").open("wb") as out, (output / f"{name}.stderr").open("wb") as err:
                result = subprocess.run(command, cwd=REPO, stdout=out, stderr=err)
            receipt["steps"].append({"name": name, "command": command, "exit": result.returncode,
                                     "elapsed_seconds": time.monotonic() - start})
            if result.returncode:
                raise RuntimeError(f"{name} exited {result.returncode}")
            if name == "fresh-parallel-first-use":
                startup_flags = [f"--output_user_root={os.environ['BAZEL_OUTPUT_USER_ROOT']}"] if os.environ.get("BAZEL_OUTPUT_USER_ROOT") else []
                testlogs = Path(subprocess.check_output(
                    ["python3", wrapper, *startup_flags, "--noexperimental_remote_repo_contents_cache",
                     "info", config, *platform_flags, *host_flags, "bazel-testlogs"], cwd=REPO, text=True,
                ).strip())
                copy_test_result(output, "v8-poc", "fresh-parallel-first-use", testlogs)
                text = (output / "fresh-parallel-first-use.log").read_text()
                if f"test {REGRESSION} ... ok" not in text or "1 passed; 0 failed; 0 ignored" not in text:
                    raise RuntimeError("fresh-process parallel allocator regression did not execute")
            if name == "original-consumer-tests":
                receipt["original_test_counts"] = {}
                for package in PACKAGES:
                    copy_test_result(output, package, package, testlogs)
                    text = (output / f"{package}.log").read_text()
                    counts = re.findall(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", text)
                    if not counts or any(int(row[0]) == 0 or any(int(value) for value in row[1:]) for row in counts):
                        raise RuntimeError(f"{package} did not pass its full original tests without exclusions")
                    suites = ET.fromstring((output / f"{package}.xml").read_bytes()).iter("testsuite")
                    if any(int(suite.get("failures", "0")) or int(suite.get("errors", "0")) for suite in suites):
                        raise RuntimeError(f"{package} test XML records failure")
                    receipt["original_test_counts"][package] = counts
                if "test tests::sandbox_feature_matches_linked_v8 ... ok" not in (output / "v8-poc.log").read_text():
                    raise RuntimeError("original sandbox feature assertion did not pass")
                if "linked_v8_has_sandbox_enabled ... ok" not in (output / "code-mode-runtime.log").read_text():
                    raise RuntimeError("original runtime sandbox requirement did not pass")
            if name == "original-clippy-selector":
                selected = (output / f"{name}.stdout").read_text().splitlines()
                # The original selector intentionally excludes the PoC. Keep
                # that contract and additionally lint its binary explicitly.
                if "-//codex-rs/v8-poc:all" not in selected:
                    raise RuntimeError("original selector changed its PoC exclusion")
                if any(target + "-bin" not in selected for target in TARGETS[1:]):
                    raise RuntimeError("original selector omitted a complete consumer test")
        if snapshot() != before:
            raise RuntimeError("qualification changed a committed input")
        receipt["status"] = "passed"
    finally:
        receipt["source_after"] = snapshot()
        receipt["source_inputs_unchanged"] = receipt["source_after"] == before
        receipt["outputs"] = {path.name: {"bytes": path.stat().st_size,
                                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                              for path in sorted(output.iterdir()) if path.is_file() and path.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
