"""Build real helpers and run only Windows sandbox scoped lint; interruption never passes."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time

import mem_windows_sandbox_fix_support as evidence


PLAN_PATH = ".github/fixtures/mem-windows-sandbox-fix-plan.json"
WORKFLOW_PATH = ".github/workflows/hepta-mem-windows-sandbox-fix.yml"
FIX_COMMAND = ["just", "fix", "--locked", "-p", "codex-windows-sandbox"]

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


def run(source, records, harness, plan):
    result = {
        "schema": "mem-windows-sandbox-fix-original-run-v1", "status": "running",
        "source_head": plan["source_head"], "source_tree": plan["source_tree"],
        "harness_sha": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "job": os.environ.get("GITHUB_JOB"),
        "started_at": evidence.utc_now().isoformat(), "phases": [],
        "native_test_commands": [], "native_tests_executed": 0, "direct_model_requests_issued_by_driver": 0,
        "physical_network_request_count": None,
        "provider_boundary": "This driver builds helpers and runs scoped lint only; no test or model command is launched. Dependency-download traffic is not counted as model traffic.",
        "supervision": "One Actions 65-minute job, including setup, all commands and collection; no PID cancellation or per-phase timer reset.",
        "unknown_rule": "A missing command exit/after receipt is UNKNOWN, never a successful phase.",
    }
    if (records / "RESULT.json").exists():
        raise ValueError("this execution identity already exists; no replay")
    evidence.write_json(records / "RESULT.json", result)
    helpers = []
    fix_passes = []
    try:
        if (plan["schema"] != "mem-windows-sandbox-fix-frozen-plan-v1"
                or plan["scoped_fix_command"] != FIX_COMMAND
                or plan["native_test_commands"] != []
                or plan["job_timeout_minutes"] != 65):
            raise ValueError("qualification plan differs from the single reviewed scoped lint")
        if os.name != "nt":
            raise ValueError("this qualification requires a native Windows runner")
        if any(os.environ.get(name) != value for name, value in POLICY.items()):
            raise ValueError("compiler/resource policy differs")
        forbidden = sorted(name for name in os.environ if name in FORBIDDEN_ENV_NAMES
                           or name.startswith(FORBIDDEN_ENV_PREFIXES))
        if forbidden:
            raise ValueError(f"unsupported inherited qualification configuration names: {forbidden}")
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
        case_temp = records.parent / f"mem-windows-sandbox-fix-temp-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
        case_temp.mkdir(exist_ok=False)
        physical_temp = case_temp.resolve(strict=True)
        evidence.write_json(records / "temporary-environment.json", {
            "originalTemp": os.environ.get("TEMP"), "originalTmp": os.environ.get("TMP"),
            "physicalBuildTemp": str(physical_temp),
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
        stages.append({"id": "fix-codex-windows-sandbox", "kind": "fix", "command": FIX_COMMAND})
        result["planned_stages"] = stages
        evidence.write_json(records / "RESULT.json", result)

        for number, stage in enumerate(stages, 1):
            prefix = f"phase-{number}-{stage['id']}"
            before = evidence.snapshot(source, records / f"{prefix}-source-before")
            evidence.require_source(before)
            tools_before = tools_snapshot(source, records / f"{prefix}-tools-before")
            if before != baseline or tools_before != initial_tools:
                raise ValueError("source or tools changed before the next stage")
            helpers_before = helper_snapshot(helpers)
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
                if completed.returncode:
                    raise ValueError("the original command returned nonzero")
                phase["status"] = "command_checks_passed"
            except BaseException as error:
                phase.update(status="failed_or_interrupted", error=f"{type(error).__name__}: {error}")
            finally:
                # Only an acknowledged exit plus unchanged source/tools/helpers
                # may settle a stage. Unknown execution never starts another.
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
                raise ValueError(f"{prefix} failed or has unknown execution/integrity; subsequent commands stopped")
            if stage["kind"] == "fix":
                fix_passes.append(stage["id"])

        final = evidence.snapshot(source, records / "source-after")
        evidence.require_source(final)
        if final != baseline:
            raise ValueError("final source differs")
        if fix_passes != ["fix-codex-windows-sandbox"]:
            raise ValueError("the one required scoped lint did not finish cleanly")
        result.update(
            status="passed_one_clean_windows_sandbox_fix",
            after=final, helpers_after=helper_snapshot(helpers),
            clean_scoped_fixes=fix_passes,
            remaining_job_seconds_after=evidence.budget(records),
        )
    except BaseException as error:
        result.update(status="failed_or_interrupted", error=f"{type(error).__name__}: {error}")
    finally:
        result["finished_at"] = evidence.utc_now().isoformat()
        evidence.write_json(records / "RESULT.json", result)
    return 0 if result["status"] == "passed_one_clean_windows_sandbox_fix" else 1


def collect(source, records):
    observation = {"status": "partial_or_failed", "collected_at": evidence.utc_now().isoformat()}
    try:
        observation["source"] = evidence.snapshot(source, records / "source-at-collection")
        result = json.loads((records / "RESULT.json").read_text())
        evidence.require_source(observation["source"])
        if result["status"] == "passed_one_clean_windows_sandbox_fix" and result["after"] == observation["source"]:
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
