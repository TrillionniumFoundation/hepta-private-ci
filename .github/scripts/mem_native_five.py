"""Run only the frozen five-case Windows plan; interrupted work never passes."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

import mem_native_five_support as evidence


PLAN_PATH = ".github/fixtures/mem-native-five-plan.json"
WORKFLOW_PATH = ".github/workflows/hepta-mem-native-five.yml"
JUNIT_PATH = "codex-rs/target/nextest/local/junit.xml"
GROUPS = [
    {
        "id": "matched-responses-loopback", "package": "core_test_support",
        "binary_id": "core_test_support", "target_args": ["--lib"],
        "cases": ["responses::matcher_tests::matched_response_helpers_record_only_accepted_requests"],
    },
    {
        "id": "original-subagent-hooks", "package": "codex-core",
        "binary_id": "codex-core::all", "target_args": ["--test", "all"],
        "cases": [
            "suite::subagent_notifications::subagent_start_replaces_session_start_and_injects_context",
            "suite::subagent_notifications::subagent_stop_replaces_stop_and_skips_internal_subagents",
        ],
    },
    {
        "id": "setup-pipe-and-original-leak", "package": "codex-windows-sandbox",
        "binary_id": "codex-windows-sandbox", "target_args": ["--lib"],
        "cases": [
            "setup::isolated_process::tests::non_elevated_setup_excludes_ambient_pipe_handles",
            "unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit",
        ],
    },
]
for _group in GROUPS:
    _group["filter"] = " | ".join(f"test(={name})" for name in _group["cases"])

POLICY = {
    "RUSTUP_TOOLCHAIN": "1.96.0", "CARGO_BUILD_JOBS": "1",
    "CARGO_INCREMENTAL": "0", "CARGO_PROFILE_DEV_DEBUG": "0",
    "CARGO_PROFILE_TEST_DEBUG": "0", "CARGO_TERM_COLOR": "never",
    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
}
FORBIDDEN_ENV_PREFIXES = (
    "HEPTA_LOCAL_PROVIDER_", "HEPTA_MEM_CONTEXT_", "HEPTA_NATIVE_",
    "NEXTEST_", "CARGO_BIN_EXE_", "RUNFILES_",
)
FORBIDDEN_ENV_NAMES = {
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE",
    "CODEX_TEST_REMOTE_EXEC_SERVER_URL", "CODEX_TEST_ENVIRONMENT",
    "CODEX_SANDBOX_NETWORK_DISABLED",
}


def load_source_runner(source):
    path = source / ".github/scripts/windows_current_ci.py"
    spec = importlib.util.spec_from_file_location("frozen_windows_current_ci", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tools_snapshot(source, directory):
    tools = evidence.tools_snapshot(source, directory)
    for name, command, prefix in [
        ("cargo-nextest", ["cargo", "nextest", "--version"], "cargo-nextest 0.9.103"),
        ("python", ["python", "--version"], "Python 3."),
        ("python3", ["python3", "--version"], "Python 3."),
    ]:
        process = subprocess.run(command, cwd=source / "codex-rs", capture_output=True)
        (directory / f"{name}.stdout").write_bytes(process.stdout)
        (directory / f"{name}.stderr").write_bytes(process.stderr)
        version = process.stdout.decode("utf-8").strip()
        version_ok = version.startswith(prefix)
        if name == "cargo-nextest":
            version_ok = version == prefix or version.startswith(prefix + " ")
        if process.returncode or not version_ok:
            raise ValueError(f"missing or wrong required tool: {name}")
        binary = shutil.which(name)
        if not binary:
            raise ValueError(f"missing actual tool executable: {name}")
        path = Path(binary).resolve(strict=True)
        tools[name] = {"path": str(path), "version": version, **evidence.digest(path)}
    evidence.write_json(directory / "tools.json", tools)
    return tools


def helper_snapshot(bindings):
    result = []
    for row in bindings:
        source = Path(row["source"])
        sibling = Path(row["testSibling"])
        if source.is_symlink() or sibling.is_symlink():
            raise ValueError("helper path became redirected")
        before = evidence.digest(source)
        after = evidence.digest(sibling)
        if before != after or before != {key: row[key] for key in ("bytes", "sha256")}:
            raise ValueError("actual helper executable bytes changed")
        result.append(row)
    return result


def parse_junit(raw, log, group, started_at, finished_at, seen_uuids):
    if len(raw) > 32 * 1024 * 1024 or b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("JUnit is oversized or contains a document declaration")
    root = ET.fromstring(raw)
    if root.tag != "testsuites":
        raise ValueError("unexpected JUnit root")
    observed_uuid = str(uuid.UUID(root.attrib["uuid"]))
    log_uuids = {str(uuid.UUID(value)) for value in re.findall(
        r"Nextest run ID\s+([0-9a-fA-F-]{36})", log, re.IGNORECASE,
    )}
    if log_uuids != {observed_uuid} or observed_uuid in seen_uuids:
        raise ValueError("JUnit does not bind to one fresh original nextest run")
    observed_time = datetime.fromisoformat(root.attrib["timestamp"].replace("Z", "+00:00"))
    start = datetime.fromisoformat(started_at)
    finish = datetime.fromisoformat(finished_at)
    if any(value.tzinfo is None for value in (observed_time, start, finish)):
        raise ValueError("JUnit and command times must carry their actual timezone")
    # Nextest serializes millisecond precision; compare at that same precision.
    if not int(start.timestamp() * 1000) <= int(observed_time.timestamp() * 1000) <= int(finish.timestamp() * 1000):
        raise ValueError("JUnit timestamp lies outside the actual command interval")
    expected = sorted(group["cases"])
    cases = list(root.iter("testcase"))
    observed = sorted(case.attrib["name"] for case in cases)
    if observed != expected or any(case.attrib.get("classname") != group["binary_id"] for case in cases):
        raise ValueError("JUnit case identities differ from the exact selected scope")
    suites = list(root.findall("testsuite"))
    if len(suites) != 1 or suites[0].attrib.get("name") != group["binary_id"]:
        raise ValueError("JUnit binary identity differs")
    if int(root.attrib["tests"]) != len(expected):
        raise ValueError("JUnit total differs from the fixed case set")
    passed = (
        int(root.attrib["failures"]) == int(root.attrib["errors"]) == 0
        and int(suites[0].attrib.get("disabled", "0")) == 0
        and all(child.tag in {"system-out", "system-err"} for case in cases for child in case)
    )
    seen_uuids.add(observed_uuid)
    return {"uuid": observed_uuid, "timestamp": root.attrib["timestamp"],
            "binary_id": group["binary_id"], "cases": observed, "passed": passed}


def retain_junit(source, records, prefix, log, group, phase, seen_uuids):
    path = source / JUNIT_PATH
    if path.is_symlink() or not path.is_file() or path.resolve() != path:
        raise ValueError("the exact current JUnit path is absent or redirected")
    raw = path.read_bytes()
    destination = records / f"{prefix}.junit.xml"
    if destination.exists():
        raise ValueError("JUnit destination already exists; no receipt replay")
    before = evidence.digest(path)
    # Only this newly generated, pre-admitted diagnostic artifact is relocated.
    # No source edit or unrelated untracked file is removed or accepted.
    path.rename(destination)
    if destination.read_bytes() != raw or evidence.digest(destination) != before:
        raise ValueError("JUnit changed during its retained relocation")
    phase["junit_artifact"] = {
        "original_path": JUNIT_PATH, "retained_path": destination.name,
        **before, "source_artifact_was_absent_before_command": True,
        "same_volume_rename": True,
    }
    return parse_junit(raw, log, group, phase["started_at"], phase["command_finished_at"], seen_uuids)


def run(source, records, harness, plan):
    result = {
        "schema": "mem-native-five-original-run-v1", "status": "running",
        "source_head": plan["source_head"], "source_tree": plan["source_tree"],
        "harness_sha": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "job": os.environ.get("GITHUB_JOB"),
        "started_at": evidence.utc_now().isoformat(), "phases": [],
        "native_groups": plan["groups"], "direct_model_requests_issued_by_driver": 0,
        "physical_network_request_count": None,
        "provider_boundary": "The selected Rust fixtures use local loopback mocks; this driver makes no provider request and does not instrument all network requests.",
        "supervision": "One Actions 65-minute job, including setup, all commands and collection; no PID cancellation or per-phase timer reset.",
        "unknown_rule": "A missing command exit/after receipt is UNKNOWN, never a successful phase.",
    }
    if (records / "RESULT.json").exists():
        raise ValueError("this execution identity already exists; no replay")
    evidence.write_json(records / "RESULT.json", result)
    helpers = []
    seen_uuids = set()
    native_failed = False
    native_passes = []
    fix_passes = []
    try:
        if plan["schema"] != "mem-native-five-frozen-plan-v1" or plan["groups"] != GROUPS:
            raise ValueError("qualification plan differs from the reviewed five active cases")
        if os.name != "nt":
            raise ValueError("this qualification requires a native Windows runner")
        if any(os.environ.get(name) != value for name, value in POLICY.items()):
            raise ValueError("compiler/resource policy differs")
        forbidden = sorted(name for name in os.environ if name in FORBIDDEN_ENV_NAMES
                           or name.startswith(FORBIDDEN_ENV_PREFIXES))
        if forbidden:
            raise ValueError(f"unsupported inherited qualification configuration names: {forbidden}")
        if source.drive.lower() != records.drive.lower():
            raise ValueError("source and records must support the original JUnit's same-volume retained move")
        harness_head = evidence.git(harness, "rev-parse", "HEAD").decode().strip()
        if harness_head != os.environ["GITHUB_SHA"] or evidence.git(harness, "status", "--porcelain=v1", "--untracked-files=all"):
            raise ValueError("harness is not its exact clean event commit")
        result["harness"] = {
            "head": harness_head, "tree": evidence.git(harness, "rev-parse", "HEAD^{tree}").decode().strip(),
            "driver": evidence.digest(Path(__file__)), "support": evidence.digest(Path(evidence.__file__)),
            "workflow": evidence.digest(harness / WORKFLOW_PATH), "input": evidence.digest(harness / PLAN_PATH),
        }
        for name, expected in plan["files"].items():
            path = source / name
            if path.is_symlink() or evidence.digest(path) != {key: expected[key] for key in ("bytes", "sha256")}:
                raise ValueError(f"frozen source dependency differs: {name}")
        baseline = evidence.snapshot(source, records / "source-before")
        evidence.require_source(baseline)
        target = Path(os.environ["CARGO_TARGET_DIR"]).resolve()
        if any(target.is_relative_to(path) or path.is_relative_to(target) for path in (source, harness, records)):
            raise ValueError("build target must be independent of source, harness and evidence")
        target.mkdir(exist_ok=False)
        case_temp = records.parent / f"mem-native-five-case-temp-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
        case_temp.mkdir(exist_ok=False)
        physical_temp = case_temp.resolve(strict=True)
        evidence.write_json(records / "temporary-environment.json", {
            "originalTemp": os.environ.get("TEMP"), "originalTmp": os.environ.get("TMP"),
            "physicalCaseTemp": str(physical_temp),
            "sandbox_skip_environment_present": False,
            "sandbox_environment_modified": False,
        })
        os.environ["TEMP"] = os.environ["TMP"] = str(physical_temp)
        initial_tools = tools_snapshot(source, records / "tools-before")
        source_runner = load_source_runner(source)
        stages = [{"id": "build-sandbox-helpers", "kind": "helpers", "command": [
            "cargo", "build", "--locked", "-p", "codex-windows-sandbox", "--profile", "dev-small",
            "--message-format=json", "--bin", "codex-windows-sandbox-setup", "--bin", "codex-command-runner",
        ]}]
        for group in plan["groups"]:
            stages.append({"id": group["id"], "kind": "native", "group": group, "command": [
                "just", "test", "--locked", "-p", group["package"], *group["target_args"],
                "--cargo-profile", "dev-small", "-E", group["filter"], "--test-threads", "1",
                "--no-tests", "fail", "--retries", "0",
            ]})
        for package in ("core_test_support", "codex-core", "codex-windows-sandbox"):
            stages.append({"id": f"fix-{package}", "kind": "fix", "command": [
                "just", "fix", "--locked", "-p", package,
            ]})
        result["planned_stages"] = [{key: value for key, value in stage.items() if key != "group"} for stage in stages]
        evidence.write_json(records / "RESULT.json", result)

        for number, stage in enumerate(stages, 1):
            prefix = f"phase-{number}-{stage['id']}"
            if native_failed and stage["kind"] == "native":
                evidence.write_json(records / f"{prefix}.not-run.json", {
                    "status": "NOT_RUN_AFTER_PRIOR_NATIVE_FAILURE", "command": stage["command"],
                    "reason": "No new native group is launched after a failed group.",
                })
                continue
            before = evidence.snapshot(source, records / f"{prefix}-source-before")
            evidence.require_source(before)
            tools_before = tools_snapshot(source, records / f"{prefix}-tools-before")
            if before != baseline or tools_before != initial_tools:
                raise ValueError("source or tools changed before the next stage")
            helpers_before = helper_snapshot(helpers)
            if (source / JUNIT_PATH).exists():
                raise ValueError("unexpected pre-existing JUnit artifact; no stale report reuse")
            phase = {
                "kind": stage["kind"], "command": stage["command"], "cwd": str(source / "codex-rs"),
                "status": "running", "started_at": evidence.utc_now().isoformat(),
                "remaining_job_seconds_before": evidence.budget(records), "before": before,
                "helpers_before": helpers_before, "command_exit_code": None, "timeout_observed": None,
            }
            result["phases"].append(prefix)
            evidence.write_json(records / "RESULT.json", result)
            evidence.write_json(records / f"{prefix}.intent.json", phase)
            started = time.monotonic()
            log_path = records / f"{prefix}.raw.log"
            try:
                with log_path.open("xb") as output:
                    completed = subprocess.run(stage["command"], cwd=source / "codex-rs",
                                               stdout=output, stderr=subprocess.STDOUT, check=False)
                    output.flush()
                    os.fsync(output.fileno())
                phase["command_exit_code"] = completed.returncode
                phase["command_finished_at"] = evidence.utc_now().isoformat()
                phase["source_immediately_after_command"] = evidence.snapshot(source, records / f"{prefix}-observed-source")
                log = source_runner.ANSI.sub("", log_path.read_text(encoding="utf-8", errors="replace"))
                if stage["kind"] == "helpers" and completed.returncode == 0:
                    helpers = source_runner.publish_sandbox_helpers(source, target, log)
                    phase["helper_binding"] = helpers
                elif stage["kind"] == "native":
                    group = stage["group"]
                    phase["native_raw_assessment"] = source_runner.assess({
                        "id": group["id"], "package": group["binary_id"],
                        "requiredTests": group["cases"], "expectedTestCount": len(group["cases"]),
                    }, completed.returncode, log)
                    phase["junit"] = retain_junit(source, records, prefix, log, group, phase, seen_uuids)
                    if not phase["native_raw_assessment"]["passed"] or not phase["junit"]["passed"]:
                        raise ValueError("native case identity/status differs; LEAK, failure, skip or missing case cannot pass")
                if completed.returncode:
                    raise ValueError("the original command returned nonzero")
                phase["status"] = "command_checks_passed"
            except BaseException as error:
                phase.update(status="failed_or_interrupted", error=f"{type(error).__name__}: {error}")
            finally:
                # A fully acknowledged native failure may be followed by the
                # separately authorized lint scope, but never after unknown
                # execution, dirty source or changed tool/helper identities.
                if phase["command_exit_code"] is not None:
                    try:
                        phase["helpers_after"] = helper_snapshot(helpers)
                        after = evidence.snapshot(source, records / f"{prefix}-source-after")
                        phase["after"] = after
                        tools_after = tools_snapshot(source, records / f"{prefix}-tools-after")
                        phase["remaining_job_seconds_after"] = evidence.budget(records)
                        evidence.require_source(after)
                        if after != before or tools_after != tools_before:
                            raise ValueError("source or tools changed during the stage")
                        if helpers_before and phase["helpers_after"] != helpers_before:
                            raise ValueError("native helper binding changed during the stage")
                        phase["post_command_integrity"] = True
                        if phase["status"] == "command_checks_passed":
                            phase.update(status="passed_clean", timeout_observed=False)
                    except BaseException as error:
                        phase.update(status="failed_or_interrupted", post_command_integrity=False,
                                     integrity_error=f"{type(error).__name__}: {error}")
                phase.update(finished_at=evidence.utc_now().isoformat(), elapsed_seconds=time.monotonic() - started)
                if log_path.exists():
                    phase["raw_log"] = {"path": log_path.name, **evidence.digest(log_path)}
                evidence.write_json(records / f"{prefix}.json", phase)
                print(json.dumps({"phase": prefix, "status": phase["status"]}), flush=True)
            if phase["status"] != "passed_clean":
                if stage["kind"] == "native" and phase.get("post_command_integrity") is True:
                    native_failed = True
                    result["native_status"] = "FAILED_OR_UNQUALIFIED_ORIGINAL_GROUP"
                    evidence.write_json(records / "RESULT.json", result)
                    continue
                raise ValueError(f"{prefix} failed or has unknown execution/integrity; subsequent commands stopped")
            if stage["kind"] == "native":
                native_passes.extend(stage["group"]["cases"])
            elif stage["kind"] == "fix":
                fix_passes.append(stage["id"])

        final = evidence.snapshot(source, records / "source-after")
        evidence.require_source(final)
        if final != baseline:
            raise ValueError("final source differs")
        native_passed = not native_failed and len(seen_uuids) == 3 and len(native_passes) == 5
        result.update(
            status="passed_five_named_cases_and_three_clean_scoped_fixes"
            if native_passed and len(fix_passes) == 3 else "failed_native_with_independent_lint_results",
            after=final, helpers_after=helper_snapshot(helpers),
            native_status="FIVE_EXACT_CASES_PASSED" if native_passed else "NOT_ALL_FIVE_CASES_QUALIFIED",
            native_passed_cases=native_passes, native_case_count=len(native_passes),
            clean_scoped_fixes=fix_passes, nextest_original_run_uuids=sorted(seen_uuids),
            remaining_job_seconds_after=evidence.budget(records),
        )
    except BaseException as error:
        result.update(status="failed_or_interrupted", error=f"{type(error).__name__}: {error}")
    finally:
        result["finished_at"] = evidence.utc_now().isoformat()
        evidence.write_json(records / "RESULT.json", result)
    return 0 if result["status"] == "passed_five_named_cases_and_three_clean_scoped_fixes" else 1


def collect(source, records):
    observation = {"status": "partial_or_failed", "collected_at": evidence.utc_now().isoformat()}
    try:
        observation["source"] = evidence.snapshot(source, records / "source-at-collection")
        result = json.loads((records / "RESULT.json").read_text())
        evidence.require_source(observation["source"])
        if result["status"] == "passed_five_named_cases_and_three_clean_scoped_fixes" and result["after"] == observation["source"]:
            helper_snapshot(result["helpers_after"])
            observation["status"] = "qualified_results_retained"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        observation["error"] = f"{type(error).__name__}: {error}"
    observation["boundary"] = "Observation only; missing exits/after receipts cannot be reconstructed as successful settlement."
    evidence.write_json(records / "COLLECTION.json", observation)
    files = []
    for path in sorted(records.rglob("*")):
        if path.is_file() and path.name != "FILE_MANIFEST.json":
            if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("artifact member is redirected or not regular")
            files.append({"path": path.relative_to(records).as_posix(), **evidence.digest(path)})
    evidence.write_json(records / "FILE_MANIFEST.json", files)
    return 0 if observation["status"] == "qualified_results_retained" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("run", "collect"))
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--records", required=True, type=Path)
    args = parser.parse_args()
    source, records = args.source.resolve(), args.records.resolve()
    harness = Path(__file__).resolve().parents[2]
    if any(a.is_relative_to(b) or b.is_relative_to(a) for a, b in ((source, records), (harness, records), (harness, source))):
        raise ValueError("source, harness and records must be independent")
    plan = json.loads((harness / PLAN_PATH).read_text())
    evidence.configure(plan)
    return run(source, records, harness, plan) if args.action == "run" else collect(source, records)


if __name__ == "__main__":
    raise SystemExit(main())
