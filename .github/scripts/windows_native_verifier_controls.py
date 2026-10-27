#!/usr/bin/env python3
"""Run independent native verifier, pipe and owned-process controls; preserve original91."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from windows_current_ci import git, source, valid_source
from windows_native_exact_cases import parse
import time


RUNNER_NAMES = [
    "elevated::runner_client::runner_process::tests::" + name
    for name in (
        "native_runner_exit_is_reaped_before_success",
        "native_runner_exit_mismatch_is_refused_after_reaping",
        "dropped_unconsumed_runner_is_terminated_and_reaped",
        "native_exit_wait_remains_cancellable_for_stalled_owned_runner",
    )
]
CRYPTO_NAMES = [
    "windows_openssh::tests::" + name
    for name in (
        "real_system32_child_and_strict_rust_accept_identical_original_bytes",
        "changed_body_is_rejected_by_strict_rust_and_actual_native_child",
        "wrong_namespace_is_rejected_by_actual_native_child",
        "captured_original_policy_dacl_change_is_refused_on_the_same_full_file_id",
    )
]
TRANSPORT_NAMES = [
    "windows_openssh::tests::transport::" + name
    for name in (
        "actual_unrelated_pipe_client_receives_no_original_bytes",
        "original_deadline_cancels_real_pending_connect_and_reaps_its_owned_child",
    )
]
GROUPS = [
    {
        "id": "owned-runner-process-four",
        "package": "codex-windows-sandbox",
        "names": RUNNER_NAMES,
        "runIgnored": False,
    },
    {
        "id": "dual-sshsig-native-four",
        "package": "codex-hepta-operator-acceptance",
        "names": CRYPTO_NAMES,
        "runIgnored": True,
    },
    {
        "id": "real-client-and-connect-timeout-two",
        "package": "codex-hepta-operator-acceptance",
        "names": TRANSPORT_NAMES,
        "runIgnored": True,
    },
]


# Reexecute this original case only as a separate process/stdio diagnostic.
# Its result is never added to original91 or to the new4+4+2 control counts.
LEAK_DIAGNOSTIC = {
    "id": "original-elevated-stdio-leak",
    "package": "codex-windows-sandbox",
    "names": ["unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit"],
    "runIgnored": False,
}


def command_for(group):
    command = [
        "just",
        "test",
        "--locked",
        "-p",
        group["package"],
        "--lib",
        "--cargo-profile",
        "dev-small",
        "-E",
        " | ".join(f"test(={name})" for name in group["names"]),
        "--test-threads",
        "1",
        "--no-tests",
        "fail",
        "--retries",
        "0",
        "--success-output",
        "immediate",
    ]
    if group["runIgnored"]:
        command.extend(["--run-ignored", "ignored-only"])
    return command


def assess_exact(group, code, text):
    expected = [[group["package"], name] for name in group["names"]]
    result = {
        "id": group["id"],
        "exitCode": code,
        "expectedIdentities": expected,
        "passed": False,
    }
    try:
        parsed = parse(text, group["package"], len(expected), expected)
        result.update(parsed)
        result["passed"] = code == 0 and all(
            row[0] == "PASS" for row in parsed["actual"]
        )
    except ValueError as error:
        result["selectionError"] = str(error)
    return result


def execute_groups(root, output, groups):
    results = []
    for group in groups:
        command = command_for(group)
        path = output / (group["id"] + ".log")
        started = time.monotonic()
        with path.open("wb") as stream:
            process = subprocess.run(
                command,
                cwd=root / "codex-rs",
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        result = assess_exact(
            group,
            process.returncode,
            path.read_text(encoding="utf-8", errors="replace"),
        )
        result.update(
            command=command,
            durationSeconds=round(time.monotonic() - started, 3),
            logSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        results.append(result)
        (output / "groups.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(result), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if sys.platform != "win32" or not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        raise RuntimeError("an actual Windows runner and exact commit are required")
    if output.is_relative_to(root) or output.exists():
        raise RuntimeError("choose a new output outside the source checkout")
    output.mkdir(parents=True)
    receipt = {
        "schema": "hepta.windows-native-verifier-controls.v1",
        "startedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "FAIL_NEW_NATIVE_CONTROLS",
        "groups": [],
        "testRetries": 0,
        "productionAuthorityGranted": False,
        "functionalQualification": False,
        "finalProductQualification": False,
        "scope": "Independent scopes: owned-process4, dual-SSHSIG4, actual-client/connect-timeout2. Never summed with original91, legacy3+3 or backend9. No whole-backend blocked-Flush timeout claim.",
    }
    tool_files = {}
    hashes = {}
    before = None
    try:
        before = source(root)
        untracked_before = git(root, "status", "--porcelain", "--untracked-files=all")
        receipt.update(
            sourceBefore=before,
            sourceStatusBefore=untracked_before,
            platform=platform.platform(),
            machine=platform.machine(),
        )
        if before["head"] != args.expected_head or untracked_before:
            raise RuntimeError("source differs from the requested clean head")
        compiler = subprocess.check_output(
            ["rustc", "--version", "--verbose"], text=True
        )
        versions = {
            "rustc": compiler,
            "cargo": subprocess.check_output(["cargo", "--version"], text=True),
            "just": subprocess.check_output(["just", "--version"], text=True),
            "nextest": subprocess.check_output(
                ["cargo", "nextest", "--version"], text=True
            ),
        }
        receipt["toolVersions"] = versions
        if not (
            compiler.startswith("rustc 1.96.0 ")
            and "host: x86_64-pc-windows-msvc" in compiler
            and versions["cargo"].startswith("cargo 1.96.0 ")
            and versions["just"].strip() == "just 1.51.0"
            and versions["nextest"].startswith("cargo-nextest 0.9.103")
        ):
            raise RuntimeError(
                "native compiler or original test runner differs from its pin"
            )
        tool_files = {
            name: Path(
                subprocess.check_output(
                    ["rustup", "which", "--toolchain", "1.96.0", name], text=True
                ).strip()
            ).resolve(strict=True)
            for name in ("rustc", "cargo")
        }
        for name in ("just", "cargo-nextest"):
            executable = shutil.which(name)
            if executable is None:
                raise RuntimeError("a pinned test runner executable is missing")
            tool_files[name] = Path(executable).resolve(strict=True)
        import ctypes

        system = ctypes.create_unicode_buffer(32768)
        count = ctypes.windll.kernel32.GetSystemDirectoryW(system, len(system))
        if count == 0 or count >= len(system):
            raise RuntimeError("actual system-directory observation failed")
        tool_files["system32-ssh-keygen"] = (
            Path(system.value) / "OpenSSH" / "ssh-keygen.exe"
        ).resolve(strict=True)
        tool_records = {
            name: {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for name, path in tool_files.items()
        }
        receipt["toolFiles"] = tool_records
        protected = [
            root / name
            for name in (
                ".github/scripts/windows_current_ci.py",
                ".github/fixtures/windows-current-ci-scope.json",
                ".github/scripts/windows_native_verifier_controls.py",
                ".github/scripts/windows_native_exact_cases.py",
                "codex-rs/Cargo.lock",
                "MODULE.bazel.lock",
                "codex-rs/hepta-operator-acceptance/src/test_support.rs",
                "codex-rs/hepta-operator-acceptance/src/windows_openssh.rs",
                "codex-rs/hepta-operator-acceptance/src/windows_openssh_identity.rs",
                "codex-rs/hepta-operator-acceptance/src/windows_openssh_image.rs",
                "codex-rs/hepta-operator-acceptance/src/windows_openssh_pipe.rs",
                "codex-rs/hepta-operator-acceptance/src/windows_openssh_tests.rs",
                "codex-rs/hepta-operator-acceptance/src/windows_openssh_transport_tests.rs",
                "codex-rs/windows-sandbox-rs/src/elevated/runner_process.rs",
                "codex-rs/windows-sandbox-rs/src/elevated/runner_process_tests.rs",
                "codex-rs/windows-sandbox-rs/src/elevated/runner_client.rs",
                "codex-rs/windows-sandbox-rs/src/elevated/runner_stdio_diagnostics.rs",
            )
        ]
        hashes = {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in protected
        }
        receipt["protectedInputSha256"] = hashes
        temporary = (
            Path(os.environ["RUNNER_TEMP"]) / "hepta-native-verifier-controls-case-temp"
        )
        temporary.mkdir(exist_ok=False)
        native_temp = temporary.resolve(strict=True)
        receipt["temporaryEnvironment"] = {
            "originalTemp": os.environ.get("TEMP"),
            "originalTmp": os.environ.get("TMP"),
            "physicalCaseTemp": str(native_temp),
        }
        os.environ["TEMP"] = os.environ["TMP"] = str(native_temp)
        raw = execute_groups(root, output, GROUPS)
        diagnostic_output = output / "runner-leak-diagnostic"
        diagnostic_output.mkdir(exist_ok=False)
        receipt["separateRunnerLeakDiagnostic"] = {
            "groups": execute_groups(root, diagnostic_output, [LEAK_DIAGNOSTIC]),
            "countedInOriginal91OrNew10": False,
            "rootCauseProven": False,
            "scope": "Read-only test-build parent/retained-runner PID and STD handle type/inherit flags; no env or command text; no stdio redirection or timeout change.",
        }
        if [row["id"] for row in raw] != [group["id"] for group in GROUPS]:
            raise RuntimeError("missing, duplicate or unknown result group")
        results = []
        for group, row in zip(GROUPS, raw):
            log = output / (group["id"] + ".log")
            result = assess_exact(
                group,
                row["exitCode"],
                log.read_text(encoding="utf-8", errors="replace"),
            )
            result.update(
                command=row["command"],
                durationSeconds=row["durationSeconds"],
                logSha256=hashlib.sha256(log.read_bytes()).hexdigest(),
            )
            results.append(result)
        after = source(root)
        untracked_after = git(root, "status", "--porcelain", "--untracked-files=all")
        intact = valid_source(args.expected_head, before, after) and not untracked_after
        intact = intact and hashes == {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in protected
        }
        tools_intact = all(
            hashlib.sha256(path.read_bytes()).hexdigest()
            == tool_records[name]["sha256"]
            for name, path in tool_files.items()
        )
        receipt.update(
            sourceAfter=after,
            sourceStatusAfter=untracked_after,
            sourceUnchanged=intact,
            toolFilesUnchanged=tools_intact,
            groups=results,
        )
        if intact and tools_intact and all(result["passed"] for result in results):
            receipt["status"] = "PASS_NEW_NATIVE_CONTROLS"
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        receipt["error"] = str(error)
    finally:
        # Actual after facts are collected even if setup/parser/compile refuses.
        # Missing observations remain explicit failures, never inferred matches.
        try:
            after = source(root)
            status_after = git(root, "status", "--porcelain", "--untracked-files=all")
            receipt["sourceAfter"] = after
            receipt["sourceStatusAfter"] = status_after
            receipt["sourceUnchanged"] = (
                before is not None
                and valid_source(args.expected_head, before, after)
                and not status_after
            )
            receipt["toolFilesAfter"] = {
                name: {
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for name, path in tool_files.items()
            }
            receipt["toolFilesUnchanged"] = (
                bool(tool_files)
                and receipt.get("toolFiles") == receipt["toolFilesAfter"]
            )
            protected_after = {
                relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
                for relative in hashes
            }
            receipt["protectedInputsUnchanged"] = (
                bool(hashes) and protected_after == hashes
            )
            if not (
                receipt["sourceUnchanged"]
                and receipt["toolFilesUnchanged"]
                and receipt["protectedInputsUnchanged"]
            ):
                receipt["status"] = "FAIL_NEW_NATIVE_CONTROLS"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            receipt["afterObservationError"] = str(error)
            receipt["status"] = "FAIL_NEW_NATIVE_CONTROLS"
    receipt["finishedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"] == "PASS_NEW_NATIVE_CONTROLS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
