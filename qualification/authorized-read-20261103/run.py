#!/usr/bin/env python3
"""Run the unchanged RPC and filesystem targets on each actual native host."""
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
TARGETS = ["//codex-rs/exec-server:exec-server-authorized_read_rpc-test",
           "//codex-rs/exec-server:exec-server-unit-tests",
           "//codex-rs/file-system:file-system-unit-tests"]
CLIPPY_TARGETS = [TARGETS[0], *[target + "-bin" for target in TARGETS[1:]]]


def snapshot():
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "codex-rs/exec-server", "codex-rs/file-system",
         "codex-rs/test-binary-support", "codex-rs/exec-server-protocol", "codex-rs/Cargo.toml",
         "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml", "MODULE.bazel", "MODULE.bazel.lock",
         "defs.bzl", ".bazelrc", ".bazelversion", "workspace_root_test_launcher.*",
         ".github/actions/prepare-bazel-ci", ".github/actions/setup-ci", ".github/actions/setup-bazel-ci",
         ".github/scripts/run_bazel_with_buildbuddy.py", ".github/scripts/run-bazel-ci.sh",
         ".github/scripts/run-bazel-query-ci.sh", "scripts/check-module-bazel-lock.sh",
         "scripts/list-bazel-clippy-targets.sh", "qualification/authorized-read-20261103",
         ".github/workflows/hepta-authorized-read-qualification.yml"], cwd=REPO,
    ).decode().split("\0")
    return {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in names if name}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", choices=["ci-windows", "ci-linux", "ci-macos"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    (output / "source-inputs.json").write_text(json.dumps(before, indent=2) + "\n")
    receipt = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
               "status": "failed", "platform": platform.platform(), "machine": platform.machine(),
               "config": args.config, "steps": []}

    def run(name, command):
        started = time.monotonic()
        with (output / (name + ".stdout")).open("wb") as stdout, (output / (name + ".stderr")).open("wb") as stderr:
            result = subprocess.run(command, cwd=REPO, stdout=stdout, stderr=stderr)
        receipt["steps"].append({"name": name, "command": command, "exit": result.returncode,
                                 "elapsed_seconds": time.monotonic() - started})
        return result.returncode

    try:
        expected_system = {"ci-windows": "Windows", "ci-linux": "Linux", "ci-macos": "Darwin"}[args.config]
        if platform.system() != expected_system or not os.environ.get("BUILDBUDDY_API_KEY"):
            raise RuntimeError("qualification requires the selected native host and original authenticated RBE")
        bash = str(Path(os.environ["AUTHORIZED_READ_BASH"]).resolve(strict=True))
        receipt["bash_executable"] = bash
        windows = args.config == "ci-windows"
        target_flags = ["--platforms=//:windows_x86_64_msvc"] if windows else []
        host_flags = ["--host_platform=//:local_windows_msvc"] if windows else []
        # Retain test.xml as well as test.log when the original CI executes a
        # selected test remotely under its minimal-download default.
        options = (["--windows-msvc-host-platform"] if windows else []) + ["--remote-download-toplevel"]
        wrapper = [bash, "./.github/scripts/run-bazel-ci.sh", "--print-failed-test-logs",
                   "--print-failed-action-summary", *options, "--"]
        if args.config == "ci-linux" and run("committed-lock-check", [bash, "./scripts/check-module-bazel-lock.sh"]):
            raise RuntimeError("original committed lock check failed")
        code = run("original-rpc-and-unit-tests", [*wrapper, "test", *target_flags, "--keep_going",
                                                   "--nocache_test_results", "--test_output=all", "--", *TARGETS])
        startup = [f"--output_user_root={os.environ['BAZEL_OUTPUT_USER_ROOT']}"] if os.environ.get("BAZEL_OUTPUT_USER_ROOT") else []
        info_code = run("original-testlog-location", ["python3", "./.github/scripts/run_bazel_with_buildbuddy.py",
                                                      *startup, "--noexperimental_remote_repo_contents_cache", "info",
                                                      f"--config={args.config}", *target_flags, *host_flags, "bazel-testlogs"])
        if info_code == 0:
            testlogs = Path((output / "original-testlog-location.stdout").read_text().strip())
            for target in TARGETS:
                package, name = target.removeprefix("//").split(":")
                for suffix in ["log", "xml"]:
                    source = testlogs / package / name / ("test." + suffix)
                    if source.is_file():
                        shutil.copyfile(source, output / (name + "." + suffix))
        if code or info_code:
            raise RuntimeError("original target or test-log lookup failed; available complete logs retained")
        receipt["test_counts"] = {}
        for target in TARGETS:
            name = target.split(":")[1]
            log = (output / (name + ".log")).read_text()
            counts = re.findall(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", log)
            if len(counts) != 1 or int(counts[0][0]) == 0 or any(int(x) for x in counts[0][1:]):
                raise RuntimeError("original complete target failed or excluded cases: " + target)
            if target == TARGETS[0] and (int(counts[0][0]) != 1 or "test authorized_read_rpc_is_capability_gated_and_denies_outside_root ... ok" not in log):
                raise RuntimeError("original capability and denial RPC test did not execute")
            suites = list(ET.fromstring((output / (name + ".xml")).read_bytes()).iter("testsuite"))
            if not suites or any(int(s.get("failures", "0")) or int(s.get("errors", "0")) for s in suites):
                raise RuntimeError("original target XML records failure")
            receipt["test_counts"][target] = counts[0]
        if run("original-clippy-selector", [bash, "./scripts/list-bazel-clippy-targets.sh"]):
            raise RuntimeError("original Clippy selector failed")
        selected = (output / "original-clippy-selector.stdout").read_text().splitlines()
        # The RPC is an ordinary unsharded rust_test covered by the original
        # package glob; the two unit wrappers require their manual binaries.
        if "//codex-rs/..." not in selected or any(target not in selected for target in CLIPPY_TARGETS[1:]):
            raise RuntimeError("original Clippy selection changed")
        if run("original-clippy", [*wrapper, "build", *target_flags, "--config=clippy", "--", *CLIPPY_TARGETS]):
            raise RuntimeError("original Clippy targets failed")
        if snapshot() != before:
            raise RuntimeError("qualification changed a committed input")
        receipt["status"] = "passed"
    finally:
        receipt["source_after"] = snapshot()
        receipt["source_inputs_unchanged"] = receipt["source_after"] == before
        receipt["outputs"] = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                              for p in sorted(output.iterdir()) if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
