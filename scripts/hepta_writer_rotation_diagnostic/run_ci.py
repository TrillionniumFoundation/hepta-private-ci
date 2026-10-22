#!/usr/bin/env python3
"""Run one original writer-rotation test with frozen observation-only additions."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib
import xml.etree.ElementTree as ET

import analyze_trace


BASE = "9d84d3adf24d78cb590986a82250fa0d9b09b9f4"
BASE_TREE = "4d0fca61293a7b2af0c64651d2629e59571745b3"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SUPPORT = "scripts/hepta_writer_rotation_diagnostic"
WORKFLOW = ".github/workflows/hepta-writer-rotation-diagnostic.yml"
CARRIER_FILES = sorted(
    [WORKFLOW] + [f"{SUPPORT}/{name}" for name in (
        "run_ci.py", "analyze_trace.py", "diagnostic.patch", "diagnostic-manifest.json",
    )]
)
PINS = {
    "diagnostic.patch": "7f6d696c2711bb8eded5ee933bda1bf4fb0267f7afe41b6923176b158146db68",
    "diagnostic-manifest.json": "6eb6822d47b3eb2610a5dcfbbd7862acabecd6bf82e8a793ee8eda50e994ed01",
    "analyze_trace.py": "f29d361fb5e190d1d8ea8d3a45d475d4272d63096c8e639cbcb0344347eb3530",
}
CONFIG = "codex-rs/.config/nextest.toml"
CONFIG_SHA = "78b998d1fcb16dfef6b243a4b18748c1b28ce2d5a28d57f1f477adf0546e5ac6"
TEST = (
    "runtime_tasks::service_generations::writer_tests::"
    "sqlite_writer_rotates_256_times_without_consuming_new_service_identities"
)
COMMAND = [
    "just", "test", "--locked", "--lib", "-p", "codex-hepta-agentd",
    "--test-threads=1", "--failure-output", "immediate", "--success-output", "immediate",
    "-E", f"test(={TEST})",
]
RECORDED_ENV = (
    "CARGO_BUILD_JOBS", "CARGO_INCREMENTAL", "CARGO_PROFILE_DEV_DEBUG",
    "CARGO_TARGET_DIR", "RUST_BACKTRACE", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS",
    "RUSTC_WRAPPER", "NEXTEST_PROFILE", "NEXTEST_USER_CONFIG_FILE", "TMPDIR",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_identity(path):
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            size += len(chunk)
            hasher.update(chunk)
    return {"bytes": size, "sha256": hasher.hexdigest()}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def git(*args):
    return subprocess.check_output(
        ["git", "--no-replace-objects", *args], cwd=ROOT,
    )


def changed_paths(*args):
    fields = git("diff", "--no-renames", "--name-status", "-z", *args).split(b"\0")
    require(fields[-1] == b"" and len(fields) % 2 == 1, "unexpected git diff format")
    return sorted((fields[i].decode(), fields[i + 1].decode())
                  for i in range(0, len(fields) - 1, 2))


def source_identity(applied):
    head = git("rev-parse", "HEAD").decode().strip()
    require(head == os.environ.get("SOURCE_SHA"), "checkout does not match SOURCE_SHA")
    require(git("rev-parse", f"{BASE}^{{tree}}").decode().strip() == BASE_TREE,
            "original base tree drift")
    git("merge-base", "--is-ancestor", BASE, "HEAD")
    require(changed_paths(BASE, "HEAD") == [("A", path) for path in CARRIER_FILES],
            "carrier must add exactly the five reviewed diagnostic files to the original base")
    require(changed_paths("--cached") == [], "index was changed")
    for name, pin in PINS.items():
        require(digest((HERE / name).read_bytes()) == pin, f"frozen diagnostic input drift: {name}")
    manifest = json.loads((HERE / "diagnostic-manifest.json").read_text())
    require(manifest["commit"] == BASE and manifest["tree"] == BASE_TREE, "manifest base drift")
    expected = sorted(("M", item["path"]) for item in manifest["files"]) if applied else []
    require(changed_paths() == expected, "unexpected tracked worktree change")
    files = []
    for item in manifest["files"]:
        path = item["path"]
        require(git("rev-parse", f"{BASE}:{path}").decode().strip() == item["preimage_git_blob"],
                f"original Git blob drift: {path}")
        identity = file_identity(ROOT / path)
        expected_hash = item["postimage_sha256" if applied else "preimage_sha256"]
        require(identity["sha256"] == expected_hash, f"source bytes drift: {path}")
        files.append({"path": path, **identity})
    config_bytes = (ROOT / CONFIG).read_bytes()
    require(digest(config_bytes) == CONFIG_SHA, "original nextest configuration was changed")
    config = tomllib.loads(config_bytes.decode())
    require(config["profile"]["default"]["slow-timeout"] == {"period": "30s", "terminate-after": 2},
            "default 60-second deadline drift")
    require(config["profile"]["default"]["retries"] == 1, "original retry policy drift")
    require(config["profile"]["local"] == {
        "inherits": "default",
        "overrides": [{"filter": "package(codex-app-server) & kind(test)",
                       "test-group": "app_server_integration_local"}],
    }, "original local profile drift")
    return {
        "base": BASE, "base_tree": BASE_TREE, "carrier_commit": head,
        "carrier_tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "observation_patch_applied": applied, "files": files,
        "nextest_config": {"path": CONFIG, "sha256": CONFIG_SHA},
        "original_timeout_seconds": 60, "original_retries": 1, "original_epochs": 256,
        "default_features_preserved": True,
    }


def prepare(output):
    write_json(output / "source-before.json", source_identity(False))
    git("apply", "--check", str(HERE / "diagnostic.patch"))
    git("apply", str(HERE / "diagnostic.patch"))
    write_json(output / "source-prepared.json", source_identity(True))
    for name in PINS:
        shutil.copyfile(HERE / name, output / name)
    shutil.copyfile(ROOT / CONFIG, output / "nextest.toml")
    manifest = json.loads((HERE / "diagnostic-manifest.json").read_text())
    for item in manifest["files"]:
        destination = output / "instrumented-source" / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / item["path"], destination)


def junit_path():
    require(bool(os.environ.get("CARGO_TARGET_DIR")), "existing setup-ci did not set CARGO_TARGET_DIR")
    return Path(os.environ["CARGO_TARGET_DIR"]) / "nextest/local/junit.xml"


def run_test(output):
    source_identity(True)
    overrides = sorted(name for name in os.environ if name.startswith("NEXTEST_"))
    require(not overrides, f"refuse inherited nextest overrides: {overrides}")
    user_config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "nextest/config.toml"
    require(not user_config.exists(), "refuse an inherited nextest user configuration")
    require(not junit_path().exists(), "refuse a pre-existing JUnit result")
    require(not (output / "test.log").exists(), "refuse a pre-existing test log")
    status = {
        "command": COMMAND, "working_directory": "codex-rs", "test": TEST,
        "environment": {name: os.environ.get(name) for name in RECORDED_ENV},
        "started": False, "completed": False,
        "profile_set_by_original_just_recipe": "local",
        "timeout_and_retry_configuration": "unchanged original repository configuration",
        "inherited_nextest_override_present": False,
    }
    write_json(output / "test-process.json", status)
    started = time.monotonic()
    with (output / "test.log").open("xb") as log:
        with subprocess.Popen(COMMAND, cwd=ROOT / "codex-rs", stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT) as process:
            status["started"] = True
            write_json(output / "test-process.json", status)
            while chunk := process.stdout.read1(65536):
                log.write(chunk)
                log.flush()
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            code = process.wait()
    status.update(completed=True, exit_code=code, elapsed_seconds=time.monotonic() - started)
    status["log"] = file_identity(output / "test.log")
    write_json(output / "test-process.json", status)
    return code if code >= 0 else 128 - code


def expected_test_phases():
    result = [(0, phase) for phase in ("fixture", "initial_open", "initial_open_complete")]
    common = ("status", "attach", "request", "receipt_and_stale_retire", "list", "quiesce",
              "retire_current", "retirement_assertions")
    handoff = ("handoff", "successor_status", "resume", "stale_write", "replace_store")
    for epoch in range(1, 257):
        result.extend((epoch, phase) for phase in common)
        if epoch < 256:
            result.extend((epoch, phase) for phase in handoff)
        result.append((epoch, "epoch_complete"))
    result.extend((256, phase) for phase in (
        "retire_timer", "host_shutdown", "current_pool_close", "final_reopen", "reopened_status",
        "retired_resume_fence", "retained_receipt", "reopened_list", "first_writer_drop",
        "reopened_pool_close", "done",
    ))
    return result


def summarize_attempt(lines):
    measurements = analyze_trace.analyze("\n".join(lines))
    matches = [analyze_trace.MARKER.search(line) for line in lines]
    events = [match.groups() for match in matches]
    actual = [(int(number), phase) for kind, _, number, phase, _ in events if kind == "TEST"]
    expected = expected_test_phases()
    require(actual == expected[:len(actual)], "original test phase prefix was not preserved")
    ids = {}
    for kind, first, last in (("OPEN", 0, 256), ("HANDOFF", 1, 255)):
        starts = [int(number) for event_kind, _, number, phase, _ in events
                  if event_kind == kind and phase == analyze_trace.PHASES[kind][0]]
        require(starts == list(range(first, first + len(starts))) and len(starts) <= last - first + 1,
                f"noncontiguous or excessive {kind} invocation identity")
        ids[kind] = starts
    complete = actual == expected
    if complete:
        require(not measurements["incomplete_invocations"], "done test has an incomplete nested phase")
        require(len(ids["OPEN"]) == 257 and len(ids["HANDOFF"]) == 255,
                "done test does not contain all original opens and handoffs")
    measurements["complete_original_phase_sequence"] = complete
    measurements["observed_opens"] = len(ids["OPEN"])
    measurements["observed_handoffs"] = len(ids["HANDOFF"])
    return measurements


def attempts_from_log(path):
    attempts = []
    with path.open(errors="replace") as stream:
        for line in stream:
            if "WRITER_ROTATION_" not in line:
                continue
            matches = list(analyze_trace.MARKER.finditer(line))
            require(len(matches) == 1, "malformed or ambiguous diagnostic marker")
            marker = matches[0]
            if marker.groups()[:4] == ("TEST", "epoch", "0", "fixture"):
                require(len(attempts) < 2, "more than the original two possible attempts")
                attempts.append([])
            require(bool(attempts), "marker appeared before an original fixture start")
            # Store the exact marker-bearing line, not unrelated build output.
            attempts[-1].append(line.rstrip("\n"))
            require(len(attempts[-1]) <= 8100, "per-attempt marker budget exceeded")
    require(bool(attempts), "no executed test diagnostic markers")
    return [summarize_attempt(lines) for lines in attempts]


def junit_identity(path):
    require(path.is_file(), "no JUnit report for the original local profile")
    require(path.stat().st_size <= 16 * 1024 * 1024, "unexpectedly large single-test JUnit report")
    document = ET.parse(path)
    cases = document.findall(".//testcase")
    require(len(cases) == 1 and cases[0].get("name") == TEST, "JUnit does not contain exactly the selected original test")
    case = cases[0]
    failure = any(case.find(tag) is not None for tag in ("failure", "error", "skipped"))
    return {
        **file_identity(path), "test": case.get("name"), "classname": case.get("classname"),
        "time": case.get("time"), "final_outcome_passed": not failure,
        "prior_failure_entries": sum(len(case.findall(tag)) for tag in (
            "flakyFailure", "flakyError", "rerunFailure", "rerunError",
        )),
    }


def summarize(output):
    summary = {
        "kind": "host_writer_rotation_phase_diagnostic_not_blocker_closure",
        "base": BASE, "test": TEST, "original_epochs": 256,
        "original_timeout_seconds": 60, "original_retries": 1,
        "instrumented_test_passed": False, "native_qualification": False,
        "noninstrumented_verification": False, "errors": [], "attempts": [],
    }
    try:
        summary["process"] = json.loads((output / "test-process.json").read_text())
        summary["log"] = file_identity(output / "test.log")
        summary["attempts"] = attempts_from_log(output / "test.log")
    except (OSError, ValueError, KeyError) as error:
        summary["errors"].append(str(error))
    try:
        report = junit_path()
        if report.is_file():
            shutil.copyfile(report, output / "junit.xml")
        summary["junit"] = junit_identity(report)
    except (OSError, ValueError, ET.ParseError) as error:
        summary["errors"].append(str(error))
    process = summary.get("process", {})
    summary["instrumented_test_passed"] = bool(
        not summary["errors"] and process.get("completed") is True
        and type(process.get("exit_code")) is int and process["exit_code"] == 0
        and summary["attempts"][-1]["complete_original_phase_sequence"]
        and summary.get("junit", {}).get("final_outcome_passed") is True
    )
    encoded = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode()) > 65536:
        summary["attempts"] = []
        summary["instrumented_test_passed"] = False
        summary["errors"].append("phase summary exceeded 64 KiB; complete raw log is retained")
        encoded = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    (output / "phase-summary.json").write_text(encoded)
    print(encoded, end="")
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(step_summary, "a") as stream:
            stream.write("## Original 256-rotation diagnostic\n\n```json\n" + encoded + "```\n")
    return 0 if summary["instrumented_test_passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "verify", "summarize"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        if args.action == "prepare":
            prepare(args.output)
        elif args.action == "run":
            return run_test(args.output)
        elif args.action == "verify":
            write_json(args.output / "source-after.json", source_identity(True))
        else:
            return summarize(args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        record = {"action": args.action, "error": str(error), "qualified": False}
        write_json(args.output / f"{args.action}-error.json", record)
        print(json.dumps(record), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
