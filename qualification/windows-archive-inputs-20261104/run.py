#!/usr/bin/env python3
"""Qualify the original process-wrapper tests and real native archive handling."""
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
TARGET = "@rules_rust//util/process_wrapper:process_wrapper_test"
ORIGINAL_CASES = set([
    "large_wrapper_prefix_preserves_all_arguments_and_child_response_files",
    "multiline_values_remain_literal_through_the_normal_flag_parser",
    "ordinary_wrapper_and_child_arguments_do_not_read_response_files",
    "test_enforce_allow_features_flag_user_didnt_say",
    "test_enforce_allow_features_flag_user_requested_something",
    "test_enforce_allow_features_flag_user_requested_something_in_param_file",
    "test_extra_args",
    "test_flag_help",
    "test_flag_single_repeated",
    "test_json_parsing_error",
    "test_process_line_diagnostic_json",
    "test_process_line_diagnostic_rendered",
    "test_process_line_noise",
    "test_read_to_array",
    "test_repeated_flags",
    "test_stamp_status_to_array",
    "unreadable_wrapper_response_file_fails_before_running_the_child",
    "wrapper_response_files_cannot_change_the_child_boundary_or_recurse"
])
WINDOWS_REGRESSION = "preserve_final_archives_and_exclude_llvm_temp_files"


def complete_test_counts(log, windows):
    required = ORIGINAL_CASES | ({WINDOWS_REGRESSION} if windows else set())
    summaries = re.findall(
        r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", log)
    if summaries != [(str(len(required)), "0", "0", "0", "0")]:
        raise RuntimeError("the complete original wrapper tests did not pass")
    cases = re.findall(r"^test (\S+) \.\.\. ok$", log, re.MULTILINE)
    names = [case.rsplit("::", 1)[-1] for case in cases]
    if len(cases) != len(required) or len(set(cases)) != len(cases) or set(names) != required:
        raise RuntimeError("the original wrapper cases and applicable native regression did not execute once")
    return {"test_counts": [len(required), 0, 0, 0, 0], "original_cases": cases}


def snapshot():
    names = subprocess.check_output([
        "git", "ls-files", "-z", "--", "MODULE.bazel", "MODULE.bazel.lock", "BUILD.bazel",
        "defs.bzl", ".bazelrc", ".bazelversion", "patches", "bazel", "justfile",
        "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml",
        ".github/actions/prepare-bazel-ci", ".github/actions/setup-ci", ".github/actions/setup-bazel-ci",
        ".github/scripts/run_bazel_with_buildbuddy.py", ".github/scripts/run-bazel-ci.sh",
        ".github/scripts/run-bazel-query-ci.sh", "scripts/check-module-bazel-lock.sh",
        "scripts/list-bazel-clippy-targets.sh", "qualification/windows-archive-inputs-20261104", ".github/workflows/hepta-windows-archive-input-qualification.yml",
    ], cwd=ROOT).decode().split("\0")
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names if name}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", choices=["ci-windows", "ci-linux"], required=True)
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
        bash = str(Path(os.environ["PROCESS_WRAPPER_QUALIFICATION_BASH"]).resolve(strict=True))
        receipt["bash_executable"] = bash
        windows = args.config == "ci-windows"
        targets = ["--platforms=//:windows_x86_64_msvc"] if windows else []
        hosts = ["--host_platform=//:local_windows_msvc"] if windows else []
        options = (["--windows-msvc-host-platform"] if windows else []) + ["--remote-download-toplevel"]
        wrapper = [bash, "./.github/scripts/run-bazel-ci.sh", "--print-failed-test-logs",
                   "--print-failed-action-summary", *options, "--"]
        if args.config == "ci-linux" and run("committed-lock-check", [bash, "./scripts/check-module-bazel-lock.sh"]):
            raise RuntimeError("original committed lock check failed")
        code = run("original-process-wrapper-tests", [*wrapper, "test", *targets, "--keep_going",
                                                  "--nocache_test_results", "--test_output=all", "--", TARGET])
        startup = [f"--output_user_root={os.environ['BAZEL_OUTPUT_USER_ROOT']}"] if os.environ.get("BAZEL_OUTPUT_USER_ROOT") else []
        info = run("original-testlog-location", ["python3", "./.github/scripts/run_bazel_with_buildbuddy.py",
                                                *startup, "--noexperimental_remote_repo_contents_cache", "info",
                                                f"--config={args.config}", *targets, *hosts, "bazel-testlogs"])
        if info == 0:
            directory = Path((output / "original-testlog-location.stdout").read_text().strip())
            for suffix in ["log", "xml"]:
                source = directory / "external/rules_rs++rules_rust+rules_rust/util/process_wrapper/process_wrapper_test" / ("test." + suffix)
                if source.is_file():
                    shutil.copyfile(source, output / ("wrapper." + suffix))
        if (output / "wrapper.log").is_file():
            print((output / "wrapper.log").read_text(encoding="utf-8")[-50000:], flush=True)
        if code or info:
            raise RuntimeError("original target failed; all available test evidence retained")
        log = (output / "wrapper.log").read_text()
        receipt.update(complete_test_counts(log, windows))
        suites = list(ET.fromstring((output / "wrapper.xml").read_bytes()).iter("testsuite"))
        if not suites or any(int(s.get(key, "0")) for s in suites for key in ["failures", "errors", "skipped"]):
            raise RuntimeError("original Bazel wrapper XML did not pass")
        if any(list(s.iter("skipped")) for s in suites):
            raise RuntimeError("original Bazel wrapper was skipped")
        if run("materialized-wrapper-location", [
            "python3", "./.github/scripts/run_bazel_with_buildbuddy.py", *startup,
            "--noexperimental_remote_repo_contents_cache", "info",
            f"--config={args.config}", *targets, *hosts, "output_base",
        ]):
            raise RuntimeError("actual materialized wrapper location unavailable")
        base = Path((output / "materialized-wrapper-location.stdout").read_text().strip())
        external = base / "external/rules_rs++rules_rust+rules_rust/util/process_wrapper"
        binding = json.loads((Path(__file__).parent / "source-binding.json").read_text())
        receipt["materialized_sources"] = {}
        for name, key in [("main.rs", "candidate_main_sha256"),
                          ("windows_archive_tests.rs", "candidate_test_sha256")]:
            source = (external / name).read_bytes()
            digest = hashlib.sha256(source).hexdigest()
            if digest != binding[key]:
                raise RuntimeError("actual patched wrapper source mismatch: " + name)
            (output / ("materialized-" + name)).write_bytes(source)
            receipt["materialized_sources"][name] = {"bytes": len(source), "sha256": digest}
        if run("native-regression-format", [
            "rustfmt", "+1.96.0", "--check", str(external / "windows_archive_tests.rs"),
        ]):
            raise RuntimeError("new native regression formatting failed")
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
