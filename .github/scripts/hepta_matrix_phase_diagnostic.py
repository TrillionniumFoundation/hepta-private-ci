"""Diagnose the original Matrix startup failure without changing its limits."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time


SDK_PATH = Path("codex-rs/hepta-matrix-sdk/src/sdk.rs")
SDK_SHA256 = "3061024c6e84abd962b3933f2e974d744aba6d7f1ea2a0020720dd632e9268e5"
DIAGNOSTIC_SHA256 = "4af146ae73d0d1e5fb442558672ec1eb034fe5d5a4c23bf25e156be86c2b3386"
TEST_PATH = Path("codex-rs/hepta-matrix-sdk/tests/storage_upgrade.rs")
TEST_SHA256 = "0c8afc74027288ca994f9ab06a4026a795bee625c99ab2d15f0f469bc3bff274"
TARGET = "//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk-storage_upgrade-test"
CASES = (
    "legacy_encrypted_storage_migrates_and_reopens_with_the_same_identity",
    "wrong_passphrase_preserves_the_existing_encrypted_store",
)


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def diagnostic_source(original):
    """Reproduce the exact temporary source already exercised on native macOS."""
    if sha256(original) != SDK_SHA256:
        raise ValueError("Matrix SDK source differs from the diagnosed revision")
    source = original.decode()
    needle = "        let sidecar = tokio::time::timeout(\n"
    assert source.count(needle) == 3
    source = source.replace(
        needle, "        let phase_start = std::time::Instant::now();\n" + needle
    )
    needle = "        .map_err(|_| MatrixSdkError::Initialization)??;"
    assert source.count(needle) == 3
    source = source.replace(
        needle,
        """        .map_err(|_| {
            eprintln!("matrix-phase build_timeout elapsed_ms={}", phase_start.elapsed().as_millis());
            MatrixSdkError::Initialization
        })??;""",
    )
    needle = "        let paths = MatrixSdkPaths::prepare(layout, &config)?;"
    assert source.count(needle) == 1
    source = source.replace(
        needle,
        """        let phase_start = std::time::Instant::now();
        eprintln!("matrix-phase build_enter");
        let paths = MatrixSdkPaths::prepare(layout, &config)?;
        eprintln!("matrix-phase paths_ready elapsed_ms={}", phase_start.elapsed().as_millis());""",
    )
    start = source.index("    async fn build(")
    end = source.index("\n    pub fn client(", start)
    body = source[start:end]
    needle = "            .map_err(|_| MatrixSdkError::Initialization)?;"
    assert body.count(needle) == 3
    for error, success in (
        ("builder_error", "builder_complete"),
        ("sync_token_error", "sync_token_removed"),
        ("callback_error", "callbacks_registered"),
    ):
        body = body.replace(
            needle,
            """            .map_err(|_| {
                eprintln!("matrix-phase """
            + error
            + """ elapsed_ms={}", phase_start.elapsed().as_millis());
                MatrixSdkError::Initialization
            })?;
        eprintln!("matrix-phase """
            + success
            + """ elapsed_ms={}", phase_start.elapsed().as_millis());""",
            1,
        )
    result = (source[:start] + body + source[end:]).encode()
    assert sha256(result) == DIAGNOSTIC_SHA256
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--check-source", action="store_true")
    options = parser.parse_args()
    repo = options.repo.resolve()
    sdk = repo / SDK_PATH
    fixture = repo / TEST_PATH
    original = sdk.read_bytes()
    diagnostic = diagnostic_source(original)
    assert sha256(fixture.read_bytes()) == TEST_SHA256
    if options.check_source:
        print(json.dumps({"sdk": SDK_SHA256, "diagnostic": DIAGNOSTIC_SHA256, "fixture": TEST_SHA256}))
        return
    if options.report_dir is None:
        parser.error("--report-dir is required for execution")
    if platform.system() != "Darwin":
        raise RuntimeError("This diagnostic requires the original native macOS platform")
    out = options.report_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    commands = []

    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2) + "\n")

    def run(name, arguments):
        log = out / f"{name}.log"
        started = time.monotonic()
        with log.open("wb") as stream:
            result = subprocess.run(arguments, cwd=repo, stdout=stream, stderr=subprocess.STDOUT)
        row = {
            "name": name,
            "argv": arguments,
            "exit": result.returncode,
            "seconds": round(time.monotonic() - started, 3),
            "sha256": sha256(log.read_bytes()),
            "bytes": log.stat().st_size,
            "sdk_sha256": sha256(sdk.read_bytes()),
        }
        commands.append(row)
        save("results.json", commands)
        print(json.dumps(row), flush=True)
        assert sha256(fixture.read_bytes()) == TEST_SHA256
        return result.returncode

    subprocess.run(["git", "diff", "--exit-code"], cwd=repo, check=True)
    save(
        "source.json",
        {
            "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
            "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=repo, text=True).strip(),
            "original_failure_head": "57e489472a03515438df8ed7a0fabec882404f02",
            "original_failure_run": 43654720946,
            "original_arm_job": 132630631390,
            "sdk_sha256": SDK_SHA256,
            "diagnostic_sha256": DIAGNOSTIC_SHA256,
            "fixture_sha256": TEST_SHA256,
            "runner_os_version": platform.mac_ver()[0],
            "machine": platform.machine(),
            "tmpdir": os.environ.get("TMPDIR"),
            "runner_name": os.environ.get("RUNNER_NAME"),
            "diagnostic_only": True,
        },
    )
    (out / "source-before.rs").write_bytes(original)
    (out / "source-diagnostic.rs").write_bytes(diagnostic)
    run("runner", ["/bin/sh", "-c", "uname -a; sw_vers; sysctl hw.logicalcpu hw.physicalcpu hw.memsize; uptime"])

    def bazel(name, test_arguments, expected_cases):
        result = run(
            name,
            [
                "./.github/scripts/run-bazel-ci.sh",
                "--print-failed-action-summary",
                "--print-failed-test-logs",
                "--",
                "test",
                "--nocache_test_results",
                "--flaky_test_attempts=1",
                "--test_output=all",
                "--test_arg=--nocapture",
                f"--build_event_json_file={out / (name + '.bep.json')}",
                *test_arguments,
                "--",
                TARGET,
            ],
        )
        log = (out / f"{name}.log").read_text(errors="replace")
        log = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", log)
        observed = [
            case
            for case in expected_cases
            if re.search(rf"\btest {re.escape(case)} \.\.\. ok\b", log)
        ]
        summary = re.findall(r"test result: ok\. (\d+) passed; 0 failed;", log)
        verified = observed == list(expected_cases) and str(len(expected_cases)) in summary
        commands[-1]["expected_cases"] = list(expected_cases)
        commands[-1]["observed_passes"] = observed
        commands[-1]["successful_execution_verified"] = result == 0 and verified
        save("results.json", commands)
        return result

    try:
        bazel("original-pair", [], CASES)
        assert sdk.read_bytes() == original
        sdk.write_bytes(diagnostic)
        bazel("diagnostic-pair", [], CASES)
        for index, case in enumerate(CASES):
            assert sdk.read_bytes() == diagnostic
            bazel(
                f"diagnostic-single-{index + 1}",
                [f"--test_arg={case}", "--test_arg=--exact", "--test_arg=--test-threads=1"],
                [case],
            )
    finally:
        if sdk.read_bytes() not in (original, diagnostic):
            raise RuntimeError("Concurrent SDK mutation detected; refusing to overwrite it")
        sdk.write_bytes(original)
        save("source-restored.json", {"sha256": sha256(sdk.read_bytes()), "exact": sdk.read_bytes() == original})
    clean = run("source-clean", ["git", "diff", "--exit-code"])
    all_passed = all(
        row["exit"] == 0 and row.get("successful_execution_verified", True)
        for row in commands
    )
    save(
        "complete.json",
        {
            "complete": True,
            "all_commands_passed": all_passed,
            "sdk_source_restored": sha256(sdk.read_bytes()) == SDK_SHA256,
            "original_fixture_unchanged": sha256(fixture.read_bytes()) == TEST_SHA256,
            "original_5_second_startup_and_pbkdf2_200000_unchanged": True,
            "tmpdir_not_overridden": True,
            "ci_failure_root_cause_confirmed": False,
            "full_workspace_qualified": False,
            "diagnostic_only": True,
        },
    )
    if not all_passed or clean:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
