#!/usr/bin/env python3
"""Qualify the original complete memory target on each selected native host."""
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
TARGET = "//codex-rs/hepta-memory:hepta-memory-unit-tests"
REQUIRED = "cognitive_store_tests::v2_fixture_migrates_forward_preserving_memory_and_revoking_legacy_projection"
ORIGINAL_IGNORED = {
    "cognitive_kg_benchmark_tests::qualification_knowledge_graph_capacity_receipt",
    "cognitive_retrieval::observation::tests::target_host_owner_retrieval_reports_latency_percentiles",
    "cognitive_store_tests::kg_projection_crash_child",
    "cognitive_store_tests::qualification_kg_projection_crash_windows_restore_exact_predecessor",
    "local_compact_executor_tests::host_restart_reopen_replay_process_soak",
    "local_compact_executor_tests::sqlite_1000_operation_seeded_reopen_replay_stress",
    "local_lease_outbox_tests::qualification_durable_writer_crash_reopen_probe",
}


def complete_test_counts(log, windows):
    """Require every native test once, including the original Windows batches."""
    summaries = list(re.finditer(
        r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
        r"(\d+) measured; (\d+) filtered out", log))
    if not summaries or (not windows and len(summaries) != 1):
        raise RuntimeError("original native suite summaries are missing or duplicated")
    batches, names, ignored = [], [], []
    previous = 0
    for summary in summaries:
        counts = list(map(int, summary.groups()[1:]))
        rows = re.findall(r"^test (\S+) \.\.\. (ok|FAILED|ignored)(?:,.*)?$",
                          log[previous:summary.start()], re.MULTILINE)
        previous = summary.end()
        actual = [sum(status == value for _, status in rows)
                  for value in ["ok", "FAILED", "ignored"]]
        if actual != counts[:3] or summary.group(1) != "ok" or counts[1] or counts[3]:
            raise RuntimeError("original test case outcomes did not all pass")
        if not windows and counts[4]:
            raise RuntimeError("the original non-Windows suite was filtered")
        batches.append(counts)
        names.extend(name for name, _ in rows)
        ignored.extend(name for name, status in rows if status == "ignored")
    totals = {sum(counts) for counts in batches}
    if len(totals) != 1 or len(names) != len(set(names)) or len(names) != next(iter(totals)):
        raise RuntimeError("native batches do not form a complete disjoint suite")
    if any(line.startswith("test ") for line in log[previous:].splitlines()):
        raise RuntimeError("unaccounted native test output follows the final summary")
    if set(ignored) != ORIGINAL_IGNORED:
        raise RuntimeError("the original ignored qualification probes changed")
    if REQUIRED not in names or REQUIRED in ignored:
        raise RuntimeError("the original migration preservation/revocation test did not execute")
    passed = sum(counts[0] for counts in batches)
    if passed == 0:
        raise RuntimeError("no original test executed")
    return {"test_counts": [passed, 0, len(ignored), 0, 0],
            "native_batch_counts": batches, "original_ignored_cases": ignored,
            "unique_native_cases": len(names), "complete_disjoint_coverage": True}


def snapshot():
    names = subprocess.check_output([
        "git", "ls-files", "-z", "--", "codex-rs/hepta-memory", "codex-rs/Cargo.toml",
        "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml", "MODULE.bazel", "MODULE.bazel.lock",
        "BUILD.bazel", "defs.bzl", ".bazelrc", ".bazelversion", "workspace_root_test_launcher.*",
        ".github/actions/prepare-bazel-ci", ".github/actions/setup-ci", ".github/actions/setup-bazel-ci",
        ".github/scripts/run_bazel_with_buildbuddy.py", ".github/scripts/run-bazel-ci.sh",
        ".github/scripts/run-bazel-query-ci.sh", "scripts/check-module-bazel-lock.sh",
        "scripts/list-bazel-clippy-targets.sh", "qualification/memory-migration-20261103",
        ".github/workflows/hepta-memory-migration-qualification.yml",
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
        return result.returncode

    try:
        expected = {"ci-linux": "Linux", "ci-macos": "Darwin", "ci-windows": "Windows"}[args.config]
        if platform.system() != expected or not os.environ.get("BUILDBUDDY_API_KEY"):
            raise RuntimeError("requires the selected native host and original authenticated RBE")
        if run("committed-inputs-clean-before", ["git", "diff", "--exit-code", "HEAD", "--"]):
            raise RuntimeError("checkout differs from the source commit")
        bash = str(Path(os.environ["MEMORY_MIGRATION_BASH"]).resolve(strict=True))
        receipt["bash_executable"] = bash
        windows = args.config == "ci-windows"
        targets = ["--platforms=//:windows_x86_64_msvc"] if windows else []
        hosts = ["--host_platform=//:local_windows_msvc"] if windows else []
        options = (["--windows-msvc-host-platform"] if windows else []) + ["--remote-download-toplevel"]
        wrapper = [bash, "./.github/scripts/run-bazel-ci.sh", "--print-failed-test-logs",
                   "--print-failed-action-summary", *options, "--"]
        if args.config == "ci-linux" and run("committed-lock-check", [bash, "./scripts/check-module-bazel-lock.sh"]):
            raise RuntimeError("original committed lock check failed")
        code = run("original-memory-unit-tests", [*wrapper, "test", *targets, "--keep_going",
                                                  "--nocache_test_results", "--test_output=all", "--", TARGET])
        startup = [f"--output_user_root={os.environ['BAZEL_OUTPUT_USER_ROOT']}"] if os.environ.get("BAZEL_OUTPUT_USER_ROOT") else []
        info = run("original-testlog-location", ["python3", "./.github/scripts/run_bazel_with_buildbuddy.py",
                                                *startup, "--noexperimental_remote_repo_contents_cache", "info",
                                                f"--config={args.config}", *targets, *hosts, "bazel-testlogs"])
        if info == 0:
            directory = Path((output / "original-testlog-location.stdout").read_text().strip())
            for suffix in ["log", "xml"]:
                source = directory / "codex-rs/hepta-memory/hepta-memory-unit-tests" / ("test." + suffix)
                if source.is_file():
                    shutil.copyfile(source, output / ("memory." + suffix))
        if code or info:
            raise RuntimeError("original target failed; all available test evidence retained")
        log = (output / "memory.log").read_text()
        receipt.update(complete_test_counts(log, windows))
        suites = list(ET.fromstring((output / "memory.xml").read_bytes()).iter("testsuite"))
        if not suites or any(int(s.get(key, "0")) for s in suites for key in ["failures", "errors", "skipped"]):
            raise RuntimeError("original Bazel wrapper XML did not pass")
        if any(list(s.iter("skipped")) for s in suites):
            raise RuntimeError("original Bazel wrapper was skipped")
        if run("original-clippy-selector", [bash, "./scripts/list-bazel-clippy-targets.sh"]):
            raise RuntimeError("original Clippy selector failed")
        if TARGET + "-bin" not in (output / "original-clippy-selector.stdout").read_text().splitlines():
            raise RuntimeError("original Clippy selection changed")
        if run("original-clippy", [*wrapper, "build", *targets, "--config=clippy", "--", TARGET + "-bin"]):
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


if __name__ == "__main__":
    main()
