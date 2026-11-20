"""Compare fixed LPAC cmd entry paths without changing the original batch gate."""

import argparse
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import traceback
import uuid

from probe import (
    CHILD_SCRIPT,
    _observe_child_files,
    _observe_child_stdio,
    cleanup_fixture,
    fixture,
    observe,
    run_case,
)
from win32_api import (
    Api,
    CMD_DIAGNOSTIC_COMMANDS,
    DWORD,
    HANDLE,
    PTR,
    TOKEN_DUPLICATE,
    TOKEN_QUERY,
    WAIT_TIMEOUT,
    require,
)


MINIMAL_CHILD_SCRIPT = b"@echo off\r\nexit /b 71\r\n"


def cmd_image(api):
    system = C.create_unicode_buffer(32768)
    length = api.GetSystemDirectoryW(system, len(system))
    require(0 < length < len(system), "bounded system directory")
    path = Path(system.value) / "cmd.exe"
    size = path.stat().st_size
    require(0 < size <= 16 * 1024 * 1024, "bounded system cmd image")
    return {
        "path": str(path),
        "bytes": size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def run_inline(api, variant, user, base):
    require(
        variant
        in (
            "inline-exit71",
            "inline-stdout",
            "type-original-batch",
            "minimal-batch-exit71",
        ),
        "fixed cmd entry comparison",
    )
    record = {
        "mode": "lpac",
        "variant": variant,
        "fixed_command": CMD_DIAGNOSTIC_COMMANDS[variant],
        "diagnostic_only": True,
        "production_qualification": False,
        "child_wait_budget_ms": 5000,
        "status": "running",
    }
    profile = "hepta.ci.cmd-entry." + uuid.uuid4().hex
    package_sid, token = PTR(), HANDLE()
    created_profile = False
    root = process = capture = None
    try:
        code = api.CreateAppContainerProfile(
            profile,
            profile,
            "Owned LPAC cmd entry comparison",
            None,
            0,
            C.byref(package_sid),
        )
        require(code == 0 and package_sid.value is not None, "fresh owned profile")
        created_profile = True
        package = api.sid_text(package_sid)
        root = Path(tempfile.mkdtemp(prefix="hepta-lpac-cmd-entry-owned-"))
        record["owned_fixture"] = str(root)
        prepared = fixture(api, root, user, package, base)
        workspace = prepared["workspace"]
        record["fixture_security"] = prepared["security"]
        record["unconfined_controls"] = prepared["unconfined_controls"]
        record["child_script_sha256"] = hashlib.sha256(CHILD_SCRIPT).hexdigest()
        if variant in ("type-original-batch", "minimal-batch-exit71"):
            script_name = (
                "cmd-entry-minimal.cmd"
                if variant == "minimal-batch-exit71"
                else "child-probe.cmd"
            )
            expected_script = (
                MINIMAL_CHILD_SCRIPT
                if variant == "minimal-batch-exit71"
                else CHILD_SCRIPT
            )
            script_path = workspace / script_name
            if variant == "minimal-batch-exit71":
                # Observe the resulting security descriptor; do not assert inheritance.
                with script_path.open("xb") as stream:
                    stream.write(MINIMAL_CHILD_SCRIPT)
            script_before = script_path.read_bytes()
            record["diagnostic_script"] = {
                "path": script_name,
                "creation": (
                    "exclusive binary create without explicit security override"
                    if variant == "minimal-batch-exit71"
                    else "unchanged original fixture"
                ),
                "security_interpretation": "observed descriptor; inheritance not established",
                "bytes_before": len(script_before),
                "bytes_before_hex": script_before.hex(),
                "sha256_before": hashlib.sha256(script_before).hexdigest(),
                "security_facts_before": api.security_facts(script_path),
            }
            require(
                script_before == expected_script,
                "exact diagnostic script before launch",
            )
        capture = api.open_child_stdio(workspace)
        process = api.create_suspended(
            package_sid,
            workspace,
            lpac=True,
            stdio_handles=capture["handles"],
            diagnostic_command=variant,
        )
        api.close_child_stdio(capture)
        record["child_pid"] = process.dwProcessId
        api.checked(
            api.OpenProcessToken(
                process.hProcess, TOKEN_QUERY | TOKEN_DUPLICATE, C.byref(token)
            ),
            "query suspended inline child token",
        )
        facts = api.token_facts(token)
        record["child_token"] = facts
        require(
            facts
            == {
                "is_appcontainer": 1,
                "package_sid": package,
                "integrity_sid": "S-1-16-4096",
                "user_sid": user,
                "capability_count": 0,
            },
            "actual inline child identity differs",
        )
        query = api.lpac_token_query(token)
        record["lpac_information_class_query"] = query
        access = api.lpac_access_check(token)
        record["lpac_native_access_check"] = access
        require(
            access["access_status"]
            and access["granted_access"] == 2
            and access["privilege_count"] == 0,
            "actual inline child is not LPAC",
        )
        if query["status"] == "observed":
            require(query["value"] == 1, "LPAC query and access check disagree")
        else:
            require(
                query["status"] == "unavailable"
                and query["information_class"] == 46
                and query["error"] == 87
                and query["value"] is None,
                "unknown LPAC query result",
            )
        record["lpac_identity_basis"] = "actual child token AccessCheck"
        # Keep the original pre-resume native matrix and its separate targets.
        records = observe(api, token, root, prepared["operations"])
        record["native_operations_with_child_token"] = records
        require(api.ResumeThread(process.hThread) == 1, "resume inline child once")
        wait = api.WaitForSingleObject(process.hProcess, 5000)
        record["child_wait_result"] = wait
        require(wait == 0, "inline child exceeded original five-second budget")
        code = DWORD()
        api.checked(
            api.GetExitCodeProcess(process.hProcess, C.byref(code)), "inline child exit"
        )
        record["child_exit_code"] = code.value
        record["child_stdio"] = _observe_child_stdio(capture)
        record["child_file_observations"] = _observe_child_files(workspace)
        streams = record["child_stdio"]["streams"]
        require(
            all(
                not item["limit_exceeded"]
                and item["captured_bytes"] == item["size_bytes"]
                for item in streams
            ),
            "complete bounded inline output",
        )
        raw = {item["name"]: bytes.fromhex(item["prefix_hex"]) for item in streams}
        require(set(raw) == {"stdout.bin", "stderr.bin"}, "exact observed streams")
        expected_exit = 71 if variant == "inline-exit71" else 0
        expected_stdout = (
            b"" if variant == "inline-exit71" else b"HEPTA_LPAC_INLINE_STDOUT\r\n"
        )
        if variant == "type-original-batch":
            expected_stdout = CHILD_SCRIPT
        elif variant == "minimal-batch-exit71":
            expected_exit = 71
            expected_stdout = b""
        record["expected_exit_code"] = expected_exit
        record["expected_stdout_hex"] = expected_stdout.hex()
        record["expected_exit_observed"] = code.value == expected_exit
        record["expected_stdout_observed"] = raw["stdout.bin"] == expected_stdout
        record["diagnostic_expected_result"] = (
            record["expected_exit_observed"]
            and record["expected_stdout_observed"]
            and raw["stderr.bin"] == b""
        )
        require(
            (workspace / "child-probe.cmd").read_bytes() == CHILD_SCRIPT,
            "original batch bytes changed",
        )
        if variant in ("type-original-batch", "minimal-batch-exit71"):
            script_after = script_path.read_bytes()
            record["diagnostic_script"].update(
                {
                    "bytes_after": len(script_after),
                    "bytes_after_hex": script_after.hex(),
                    "sha256_after": hashlib.sha256(script_after).hexdigest(),
                    "security_facts_after": api.security_facts(script_path),
                }
            )
            require(
                record["diagnostic_script"]["security_facts_before"]
                == record["diagnostic_script"]["security_facts_after"],
                "diagnostic script security changed",
            )
            require(
                script_after == expected_script, "exact diagnostic script after exit"
            )
        require(
            all(row["matches_required_hypothesis"] is not False for row in records),
            "original native access matrix differs",
        )
        record["status"] = "observed"
    except Exception as error:
        record["status"] = "failed"
        record["error"] = {"type": type(error).__name__, "message": str(error)}
        record["error_traceback"] = traceback.format_exc()
    finally:
        cleanup = {}
        if process is not None:
            try:
                if api.WaitForSingleObject(process.hProcess, 0) == WAIT_TIMEOUT:
                    api.checked(
                        api.TerminateProcess(process.hProcess, 71),
                        "stop only the owned inline child",
                    )
                    require(
                        api.WaitForSingleObject(process.hProcess, 5000) == 0,
                        "owned inline child stopped",
                    )
                api.close(process.hThread)
                api.close(process.hProcess)
                cleanup["owned_child_closed"] = True
            except Exception as error:
                cleanup["owned_child_error"] = str(error)
        if capture is not None:
            try:
                api.close_child_stdio(capture)
                cleanup["owned_stdio_handles_closed"] = True
                if "child_stdio" not in record and cleanup.get("owned_child_closed"):
                    record["child_stdio"] = _observe_child_stdio(capture)
            except Exception as error:
                cleanup["owned_stdio_error"] = str(error)
        try:
            api.close(token)
            cleanup["owned_token_closed"] = True
        except Exception as error:
            cleanup["owned_token_error"] = str(error)
        try:
            cleanup_fixture(api, root, user)
            cleanup["fixture_removed"] = True
        except Exception as error:
            cleanup["fixture_error"] = str(error)
        if created_profile:
            cleanup["profile_delete_hresult"] = api.DeleteAppContainerProfile(profile)
        if package_sid.value:
            api.FreeSid(package_sid)
        record["cleanup"] = cleanup
        if (
            any(name.endswith("error") for name in cleanup)
            or cleanup.get("profile_delete_hresult", 0) != 0
        ):
            record["status"] = "failed"
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(os.name == "nt", "native Windows is required; no substitute pass")
    require(not args.output.exists(), "output must be a new receipt")
    require(
        re.fullmatch(r"[0-9a-f]{40}", args.source_head) is not None,
        "exact source commit required",
    )
    actual_head = subprocess.check_output(
        ["git", "-C", str(args.repo), "rev-parse", "HEAD"], text=True
    ).strip()
    require(actual_head == args.source_head, "checkout differs from requested head")
    sources = [
        Path(__file__),
        Path(__file__).with_name("probe.py"),
        Path(__file__).with_name("win32_api.py"),
    ]
    report = {
        "source_head": actual_head,
        "source_sha256_before": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources
        },
        "started_at": datetime.now(timezone.utc).isoformat(),
        "windows": platform.win32_ver(),
        "python": sys.version,
        "diagnostic_only": True,
        "production_qualification": False,
        "scope": "fixed LPAC inline, batch-read and minimal-batch comparisons; original whole batch required",
        "inline_cases": [],
        "batch_entry_cases": [],
    }
    api = None
    base = HANDLE()
    try:
        api = Api()
        report["cmd_image_before"] = cmd_image(api)
        api.checked(
            api.OpenProcessToken(api.GetCurrentProcess(), TOKEN_QUERY, C.byref(base)),
            "base query token",
        )
        user = api.user_sid(base)
        report["inline_cases"] = [
            run_inline(api, variant, user, base)
            for variant in ("inline-exit71", "inline-stdout")
        ]
        report["batch_entry_cases"] = [
            run_inline(api, variant, user, base)
            for variant in ("type-original-batch", "minimal-batch-exit71")
        ]
        # The original function retains every batch/native predicate and failure.
        report["original_batch_case"] = run_case(
            api, lpac=True, user=user, base_token=base
        )
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        report["error_traceback"] = traceback.format_exc()
    finally:
        try:
            if api is not None:
                api.close(base)
                report["cmd_image_after"] = cmd_image(api)
        except Exception as error:
            report["finalization_error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
        report["source_sha256_after"] = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources
        }
        report["source_unchanged"] = (
            report["source_sha256_before"] == report["source_sha256_after"]
        )
        report["cmd_image_unchanged"] = report.get(
            "cmd_image_before"
        ) is not None and report.get("cmd_image_before") == report.get(
            "cmd_image_after"
        )
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["original_batch_passed"] = (
        report.get("original_batch_case", {}).get("status")
        == "passed_bounded_hypotheses"
    )
    report["all_expected_results_observed"] = (
        "error" not in report
        and "finalization_error" not in report
        and report["source_unchanged"]
        and report["cmd_image_unchanged"]
        and len(report["inline_cases"]) == 2
        and all(
            case["status"] == "observed" and case.get("diagnostic_expected_result")
            for case in report["inline_cases"]
        )
        and len(report["batch_entry_cases"]) == 2
        and all(
            case["status"] == "observed" and case.get("diagnostic_expected_result")
            for case in report["batch_entry_cases"]
        )
        and report["original_batch_passed"]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "original_batch_passed": report["original_batch_passed"],
                "all_expected_results_observed": report[
                    "all_expected_results_observed"
                ],
            }
        )
    )
    return 0 if report["all_expected_results_observed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
