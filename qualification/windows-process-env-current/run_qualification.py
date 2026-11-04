#!/usr/bin/env python3
"""Run the original Windows Git and queue suites on an immutable current tree."""
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
INPUTS = [
    "codex-rs", ".bazelrc", ".bazelversion", "MODULE.bazel", "MODULE.bazel.lock",
    "defs.bzl", "bazel", "patches", "third_party", "scripts", "justfile",
    "workspace_root_test_launcher.bat.tpl", "workspace_root_test_launcher.sh.tpl",
    ".github/actions", ".github/scripts", "qualification/windows-process-env-current",
    "qualification/windows-process-fixtures-current",
    ".github/workflows/hepta-windows-process-env-qualification.yml",
]
TARGETS = {
    "git-utils-unit-tests": ("git-utils", 33, {
        "git_process::tests::timed_out_git_wrapper_does_not_leave_child_process_running",
        "git_process::tests::timed_out_exited_git_wrapper_does_not_leave_child_process_running",
    }),
    "queue-queue_service-test": ("ext/queue", 35, {
        "registered_queue_lifecycle_starts_messages_in_fifo_order",
        "rejected_queue_messages_remain_durable_and_block_followups",
        "two_queue_services_across_state_runtimes_submit_one_exact_binding",
    }),
}
OS_KEYS = ["ProgramFiles", "ProgramFiles(x86)", "USERPROFILE", "APPDATA",
           "LOCALAPPDATA", "ProgramData", "SystemDrive", "PATHEXT"]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshot():
    names = subprocess.check_output(
        ["git", "--no-replace-objects", "ls-files", "-z", "--", *INPUTS], cwd=ROOT
    ).decode().split("\0")
    result = {}
    for name in filter(None, names):
        path = ROOT / name
        # Bind the actual Git symlink payload rather than its resolved target.
        raw = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        result[name] = digest(raw)
    return result


def parse_reports(log_raw, xml_raw, target):
    _, count, required = TARGETS[target]
    log = log_raw.decode("utf-8-sig").replace("\r\n", "\n")
    xml = ET.fromstring(xml_raw)
    suites = xml.findall("testsuite")
    cases = xml.findall(".//testcase")
    if (len(suites) != 1 or len(cases) != 1
            or suites[0].get("tests") != "1"
            or suites[0].get("failures") != "0" or suites[0].get("errors") != "0"
            or any(cases[0].find(tag) is not None for tag in ("failure", "error", "skipped"))):
        raise RuntimeError(f"{target}: missing, failed or skipped original Bazel wrapper")
    stdout = suites[0].find("system-out")
    if stdout is None or (stdout.text or "").replace("\r\n", "\n").strip() != log.strip():
        raise RuntimeError(f"{target}: XML does not contain the retained original log")
    pattern = (r"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; "
               r"(\d+) measured; (\d+) filtered out;")
    summaries = [tuple(map(int, value)) for value in re.findall(pattern, log, re.M)]
    nested = [(1, 0, 0, 0, 32)] if target == "git-utils-unit-tests" else []
    # The existing stdin inheritance test starts its original one-test child.
    # It is not an extra outer test, and its intentional 32 filtered tests do
    # not permit filtering the complete parent suite.
    if summaries != [*nested, (count, 0, 0, 0, 0)]:
        raise RuntimeError(f"{target}: incomplete or filtered original native suite")
    names = set(re.findall(r"^test ([^\r\n]+?) \.\.\. ok$", log, re.M))
    if (len(names) != count or not required <= names or "skipping test:" in log.lower()
            or re.search(r"^test .* \.\.\. (FAILED|ignored)", log, re.M)):
        raise RuntimeError(f"{target}: missing or skipped original native case")
    return {"outer_passed": count, "outer_failed": 0, "outer_ignored": 0,
            "outer_filtered": 0, "names": sorted(names), "bazel_wrapper_cases": 1,
            "original_nested_subprocess_summaries": nested,
            "log_sha256": digest(log_raw), "xml_sha256": digest(xml_raw)}


IDLE_CASES = {
    "tasks::idle_work::tests::deferred_idle_contributors_wait_for_fence_and_preserve_registration_order",
    "tasks::idle_work::tests::deferred_idle_work_rejects_capacity_overflow",
    "tasks::idle_work::tests::cancelled_idle_fence_releases_followers_without_bypassing_their_fence",
}


def parse_idle_reports(log_raw, xml_raw):
    """Verify the explicitly selected new controls, separate from original suites."""
    log = log_raw.decode("utf-8-sig").replace("\r\n", "\n")
    xml = ET.fromstring(xml_raw)
    suites = xml.findall("testsuite")
    cases = xml.findall(".//testcase")
    if (len(suites) != 1 or len(cases) != 1 or suites[0].get("tests") != "1"
            or suites[0].get("failures") != "0" or suites[0].get("errors") != "0"
            or any(cases[0].find(tag) is not None for tag in ("failure", "error", "skipped"))):
        raise RuntimeError("deferred-idle controls: failed or missing wrapper")
    stdout = suites[0].find("system-out")
    if stdout is None or (stdout.text or "").replace("\r\n", "\n").strip() != log.strip():
        raise RuntimeError("deferred-idle controls: XML/log mismatch")
    summaries = [tuple(map(int, row)) for row in re.findall(
        r"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; "
        r"(\d+) measured; (\d+) filtered out;", log, re.M)]
    rows = re.findall(r"^test ([^\r\n]+?) \.\.\. ok$", log, re.M)
    if (len(summaries) != 1 or summaries[0][:4] != (3, 0, 0, 0)
            or len(rows) != 3 or set(rows) != IDLE_CASES
            or "skipping test:" in log.lower()
            or re.search(r"^test .* \.\.\. (FAILED|ignored)", log, re.M)):
        raise RuntimeError("deferred-idle controls: incomplete or changed case set")
    return {"passed": 3, "failed": 0, "ignored": 0, "measured": 0,
            "filtered_other_core_cases": summaries[0][4], "names": sorted(rows),
            "scope": "Only the three selected idle-work controls; not the full core suite.",
            "log_sha256": digest(log_raw), "xml_sha256": digest(xml_raw)}


def native_failure_projection(output):
    """Print bounded fixed-field diagnostics; retain arbitrary original logs in artifacts."""
    result = {}
    for target in TARGETS:
        path = output / f"{target}-test.log"
        if not path.is_file():
            result[target] = {"log_present": False}
            continue
        raw = path.read_bytes()
        log = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
        summaries = [list(map(int, row)) for row in re.findall(
            r"^test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
            r"(\d+) measured; (\d+) filtered out;", log, re.M)]
        failed = re.findall(r"^test ([A-Za-z0-9_:]+) \.\.\. FAILED$", log, re.M)
        known = TARGETS[target][2]
        result[target] = {
            "log_present": True, "bytes": len(raw), "sha256": digest(raw),
            "summaries": summaries[:4], "summary_count": len(summaries),
            "known_failed_cases": sorted(name for name in set(failed) if name in known),
            "other_failed_case_count": len(set(failed) - known),
            "parent_before_child_launch": 'wrapper stage before cleanup: Ok("parent-before-child-launch")' in log,
            "parent_after_child_launch": 'wrapper stage before cleanup: Ok("parent-after-child-launch")' in log,
            "child_script_started": 'child stage before cleanup: Ok("child-script-started")' in log,
        }
    return result


def report_paths(base, package, target, suffix):
    return sorted(base.glob(
        f"*/bazel-out/*/testlogs/codex-rs/{package}/{target}/test.{suffix}"
    ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    head = subprocess.check_output(
        ["git", "--no-replace-objects", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    tree = subprocess.check_output(
        ["git", "--no-replace-objects", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
    ).strip()
    receipt = {"source_commit": head, "source_tree": tree,
               "run_id": os.environ.get("GITHUB_RUN_ID"),
               "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
               "platform": platform.platform(), "source_before": before,
               "os_path_environment": {key: os.environ.get(key) for key in OS_KEYS},
               "pre_test_powershell_probe": False, "status": "failed", "commands": [],
               "tests": {}, "retained": [], "removed_stale_reports": []}
    try:
        if os.name != "nt" or head != os.environ["HEPTA_EXPECTED_COMMIT"]:
            raise RuntimeError("qualification requires the requested native Windows source")
        subprocess.run(["git", "--no-replace-objects", "diff", "--exit-code", "HEAD"],
                       cwd=ROOT, check=True)
        rc = (ROOT / ".bazelrc").read_text()
        if any(rc.splitlines().count(f"common:windows --test_env={key}") != 1 for key in OS_KEYS):
            raise RuntimeError("the exact eight Windows OS entries are not present once")
        base = Path(os.environ["BAZEL_OUTPUT_BASE"]) / "execroot"
        for target, (package, _, _) in TARGETS.items():
            for suffix in ("log", "xml"):
                for path in report_paths(base, package, target, suffix):
                    receipt["removed_stale_reports"].append(str(path))
                    path.unlink()
        bash = Path(os.environ["HEPTA_BASH"])
        if not bash.is_absolute() or bash.name.casefold() != "bash.exe" or not bash.is_file():
            raise RuntimeError("qualification requires the workflow's actual Git Bash executable")
        bash_bytes = bash.read_bytes()
        receipt["bash_launcher"] = {"path": str(bash), "bytes": len(bash_bytes),
                                    "sha256": digest(bash_bytes)}
        version = subprocess.run([str(bash), "--version"], cwd=ROOT, capture_output=True)
        (output / "git-bash-version.log").write_bytes(version.stdout + version.stderr)
        receipt["bash_launcher"].update(version_exit=version.returncode,
                                       version_log_sha256=digest(version.stdout + version.stderr))
        if version.returncode or not version.stdout.startswith(b"GNU bash, version "):
            raise RuntimeError("the selected workflow shell did not identify as GNU Bash")
        argv = [str(bash), ".github/scripts/run-bazel-ci.sh",
                "--print-failed-action-summary", "--print-failed-test-logs",
                "--windows-msvc-host-platform", "--remote-download-toplevel", "--",
                "test", "--platforms=//:windows_x86_64_msvc",
                "--skip_incompatible_explicit_targets", "--test_tag_filters=-argument-comment-lint",
                "--test_verbose_timeout_warnings", "--nocache_test_results", "--test_output=all",
                f"--build_metadata=COMMIT_SHA={head}", "--",
                *[f"//codex-rs/{package}:{target}" for target, (package, _, _) in TARGETS.items()]]
        start = time.monotonic()
        command_log = output / "original-process-suites.log"
        with command_log.open("wb") as stream:
            command = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        receipt["commands"].append({"argv": argv, "exit_code": command.returncode,
                                    "seconds": time.monotonic() - start,
                                    "log_sha256": digest(command_log.read_bytes())})
        errors = []
        for target, (package, _, _) in TARGETS.items():
            reports = {}
            for suffix in ("log", "xml"):
                paths = report_paths(base, package, target, suffix)
                if len(paths) != 1:
                    errors.append(f"{target}: missing or ambiguous fresh {suffix} report")
                for index, path in enumerate(paths):
                    raw = path.read_bytes()
                    label = "test" if len(paths) == 1 else f"ambiguous-{index}"
                    destination = output / f"{target}-{label}.{suffix}"
                    destination.write_bytes(raw)
                    receipt["retained"].append({"path": str(path), "file": destination.name,
                                               "bytes": len(raw), "sha256": digest(raw)})
                    if len(paths) == 1:
                        reports[suffix] = raw
            if set(reports) == {"log", "xml"}:
                try:
                    receipt["tests"][target] = parse_reports(reports["log"], reports["xml"], target)
                except (RuntimeError, ET.ParseError, UnicodeDecodeError) as error:
                    receipt["tests"][target] = {"status": "failed", "error": str(error)}
                    errors.append(str(error))
        # Compile the same current core crate and execute all three new controls.
        # Only this separate selected-control command disables core's eight shards.
        # The original 33/35 command above, its budgets and acceptance are unchanged.
        for suffix in ("log", "xml"):
            for path in report_paths(base, "core", "core-unit-tests", suffix):
                receipt["removed_stale_reports"].append(str(path))
                path.unlink()
        idle_argv = [str(bash), ".github/scripts/run-bazel-ci.sh",
                     "--windows-msvc-host-platform", "--remote-download-toplevel", "--",
                     "test", "--platforms=//:windows_x86_64_msvc",
                     "--nocache_test_results", "--test_output=all",
                     "--test_sharding_strategy=disabled",
                     "--test_arg=tasks::idle_work::tests", "--",
                     "//codex-rs/core:core-unit-tests"]
        idle_log = output / "deferred-idle-controls-command.log"
        start = time.monotonic()
        with idle_log.open("wb") as stream:
            idle_command = subprocess.run(idle_argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        receipt["commands"].append({"argv": idle_argv, "exit_code": idle_command.returncode,
                                    "seconds": time.monotonic() - start,
                                    "log_sha256": digest(idle_log.read_bytes())})
        idle_reports = {}
        for suffix in ("log", "xml"):
            paths = report_paths(base, "core", "core-unit-tests", suffix)
            if len(paths) != 1:
                errors.append(f"deferred-idle controls: missing or ambiguous {suffix}")
                continue
            raw = paths[0].read_bytes()
            destination = output / f"deferred-idle-controls-test.{suffix}"
            destination.write_bytes(raw)
            receipt["retained"].append({"path": str(paths[0]), "file": destination.name,
                                       "bytes": len(raw), "sha256": digest(raw)})
            idle_reports[suffix] = raw
        if set(idle_reports) == {"log", "xml"}:
            try:
                receipt["idle_controls"] = parse_idle_reports(idle_reports["log"], idle_reports["xml"])
            except (RuntimeError, ET.ParseError, UnicodeDecodeError) as error:
                errors.append(str(error))
        if idle_command.returncode:
            errors.append(f"deferred-idle control command exited {idle_command.returncode}")
        if command.returncode:
            errors.append(f"original Bazel command exited {command.returncode}")
        if errors:
            raise RuntimeError("; ".join(errors))
        if "Executed 2 out of 2 tests: 2 tests pass." not in command_log.read_text(errors="replace"):
            raise RuntimeError("the original two Bazel targets did not both execute")
        if snapshot() != before:
            raise RuntimeError("bound source changed during original qualification")
        subprocess.run(["git", "--no-replace-objects", "diff", "--exit-code", "HEAD"],
                       cwd=ROOT, check=True)
        receipt["status"] = "passed"
    finally:
        receipt["source_after"] = snapshot()
        receipt["source_unchanged"] = receipt["source_after"] == before
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        projection = {"status": receipt["status"], "source_commit": head,
                      "source_unchanged": receipt["source_unchanged"],
                      "native": native_failure_projection(output),
                      "idle_controls": receipt.get("idle_controls")}
        rendered = json.dumps(projection)
        if len(rendered.encode("utf-8")) > 16384:
            raise RuntimeError("process diagnostic projection exceeds its fixed output budget")
        print("PROCESS_QUALIFICATION_DIAGNOSTIC=" + rendered, flush=True)
        execution_logs = Path(os.environ["RUNNER_TEMP"]) / "bazel-execution-logs"
        if execution_logs.is_dir():
            shutil.copytree(execution_logs, output / "bazel-execution-logs")


if __name__ == "__main__":
    main()
