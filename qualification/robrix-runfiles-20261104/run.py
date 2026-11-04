#!/usr/bin/env python3
"""Qualify the complete existing Robrix corpus target on each native host."""
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

ROOT = Path(__file__).resolve().parents[2]
TARGET = "//codex-rs/hepta-supervisor:hepta-supervisor-robrix_control_projection-test"
REQUIRED = {
    "robrix_control_v2_generated_projection_and_cross_parser_corpus",
    "writer_reproduces_the_tracked_artifact_set_byte_for_byte",
}


def complete_test_counts(log):
    summaries = re.findall(
        r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", log)
    if summaries != [("2", "0", "0", "0", "0")]:
        raise RuntimeError("the complete original two-case target did not pass")
    cases = re.findall(r"^test (\S+) \.\.\. ok$", log, re.MULTILINE)
    if len(cases) != 2 or set(cases) != REQUIRED:
        raise RuntimeError("original corpus and writer cases did not both execute once")
    return {"test_counts": [2, 0, 0, 0, 0], "original_cases": cases}


def snapshot():
    names = subprocess.check_output([
        "git", "ls-files", "-z", "--", "codex-rs/hepta-supervisor", "codex-rs/utils/cargo-bin", "codex-rs/hepta-agent-protocol", "codex-rs/Cargo.toml",
        "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml", "MODULE.bazel", "MODULE.bazel.lock",
        "BUILD.bazel", "defs.bzl", ".bazelrc", ".bazelversion", "workspace_root_test_launcher.*",
        ".github/actions/prepare-bazel-ci", ".github/actions/setup-ci", ".github/actions/setup-bazel-ci",
        ".github/scripts/run_bazel_with_buildbuddy.py", ".github/scripts/run-bazel-ci.sh",
        ".github/scripts/run-bazel-query-ci.sh", "scripts/check-module-bazel-lock.sh",
        "scripts/list-bazel-clippy-targets.sh", "qualification/robrix-runfiles-20261104",
        ".github/workflows/hepta-robrix-runfiles-qualification.yml",
    ], cwd=ROOT).decode().split("\0")
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names if name}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", choices=["ci-windows", "ci-linux", "ci-macos"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    (output / "source-inputs.json").write_text(json.dumps(before, indent=2) + "\n")
    receipt = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "status": "failed", "platform": platform.platform(), "machine": platform.machine(),
               "config": args.config, "steps": []}

    def run(name, command):
        started = time.monotonic()
        with (output / (name + ".stdout")).open("wb") as stdout, (output / (name + ".stderr")).open("wb") as stderr:
            result = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr)
        receipt["steps"].append({"name": name, "command": command, "exit": result.returncode,
                                 "elapsed_seconds": time.monotonic() - started})
        if result.returncode:
            for suffix in ["stdout", "stderr"]:
                print((output / (name + "." + suffix)).read_text(encoding="utf-8", errors="replace")[-20000:], flush=True)
        return result.returncode

    try:
        expected = {"ci-linux": "Linux", "ci-macos": "Darwin", "ci-windows": "Windows"}[args.config]
        if platform.system() != expected or not os.environ.get("BUILDBUDDY_API_KEY"):
            raise RuntimeError("requires the selected native host and original authenticated RBE")
        if run("committed-inputs-clean-before", ["git", "diff", "--exit-code", "HEAD", "--"]):
            raise RuntimeError("checkout differs from the source commit")
        bash = str(Path(os.environ["ROBRIX_QUALIFICATION_BASH"]).resolve(strict=True))
        receipt["bash_executable"] = bash
        windows = args.config == "ci-windows"
        targets = ["--platforms=//:windows_x86_64_msvc"] if windows else []
        hosts = ["--host_platform=//:local_windows_msvc"] if windows else []
        options = (["--windows-msvc-host-platform"] if windows else []) + ["--remote-download-toplevel"]
        wrapper = [bash, "./.github/scripts/run-bazel-ci.sh", "--print-failed-test-logs",
                   "--print-failed-action-summary", *options, "--"]
        if args.config == "ci-linux" and run("committed-lock-check", [bash, "./scripts/check-module-bazel-lock.sh"]):
            raise RuntimeError("original committed lock check failed")
        code = run("original-robrix-corpus-tests", [*wrapper, "test", *targets, "--keep_going",
                                                  "--nocache_test_results", "--test_output=all", "--", TARGET])
        startup = [f"--output_user_root={os.environ['BAZEL_OUTPUT_USER_ROOT']}"] if os.environ.get("BAZEL_OUTPUT_USER_ROOT") else []
        info = run("original-testlog-location", ["python3", "./.github/scripts/run_bazel_with_buildbuddy.py",
                                                *startup, "--noexperimental_remote_repo_contents_cache", "info",
                                                f"--config={args.config}", *targets, *hosts, "bazel-testlogs"])
        if info == 0:
            directory = Path((output / "original-testlog-location.stdout").read_text().strip())
            for suffix in ["log", "xml"]:
                source = directory / "codex-rs/hepta-supervisor/hepta-supervisor-robrix_control_projection-test" / ("test." + suffix)
                if source.is_file():
                    shutil.copyfile(source, output / ("robrix." + suffix))
        if (output / "robrix.log").is_file():
            print((output / "robrix.log").read_text(encoding="utf-8")[-50000:], flush=True)
        if code or info:
            raise RuntimeError("original target failed; all available test evidence retained")
        log = (output / "robrix.log").read_text()
        receipt.update(complete_test_counts(log))
        suites = list(ET.fromstring((output / "robrix.xml").read_bytes()).iter("testsuite"))
        if not suites or any(int(s.get(key, "0")) for s in suites for key in ["failures", "errors", "skipped"]):
            raise RuntimeError("original Bazel wrapper XML did not pass")
        if any(list(s.iter("skipped")) for s in suites):
            raise RuntimeError("original Bazel wrapper was skipped")
        if run("original-clippy-selector", [bash, "./scripts/list-bazel-clippy-targets.sh"]):
            raise RuntimeError("original Clippy selector failed")
        if "//codex-rs/..." not in (output / "original-clippy-selector.stdout").read_text().splitlines():
            raise RuntimeError("original Clippy selection changed")
        if run("original-clippy", [*wrapper, "build", *targets, "--config=clippy", "--", TARGET]):
            raise RuntimeError("original Clippy target failed")
        if snapshot() != before or run("committed-inputs-clean-after", ["git", "diff", "--exit-code", "HEAD", "--"]):
            raise RuntimeError("qualification changed a committed input")
        receipt["status"] = "passed"
    finally:
        receipt["source_after"] = snapshot()
        receipt["source_inputs_unchanged"] = receipt["source_after"] == before
        receipt["outputs"] = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                              for p in sorted(output.iterdir()) if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("QUALIFICATION_RECEIPT " + json.dumps({key: receipt[key] for key in
              ["commit", "status", "config", "steps", "source_inputs_unchanged"]}), flush=True)


if __name__ == "__main__":
    main()
