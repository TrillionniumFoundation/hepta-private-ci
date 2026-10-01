#!/usr/bin/env python3
"""Execute bounded source mutations against learning.operator fail-closed tests."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTATION_PROFILE = "learning-operator-mutation"

MUTANTS = (
    {
        "name": "omit-training-error-budget-from-profile-digest",
        "path": "codex-rs/hepta-bellman-operator/src/profiles.rs",
        "old": "        bytes.extend_from_slice(&maximum_absolute_error.raw().to_be_bytes());\n",
        "new": "        // MUTANT: maximum error omitted from canonical identity.\n",
        "test": "mutation_profile_digest_covers_runtime_and_error_budget",
    },
    {
        "name": "omit-runtime-profile-from-training-profile-digest",
        "path": "codex-rs/hepta-bellman-operator/src/profiles.rs",
        "old": (
            "        bytes.extend_from_slice(&maximum_absolute_error.raw().to_be_bytes());\n"
            "        bytes.extend_from_slice(runtime_profile_digest.as_array());\n"
        ),
        "new": (
            "        bytes.extend_from_slice(&maximum_absolute_error.raw().to_be_bytes());\n"
            "        // MUTANT: runtime profile omitted from training identity.\n"
        ),
        "test": "mutation_profile_digest_covers_runtime_and_error_budget",
    },
    {
        "name": "omit-world-model-sensor-from-profile-digest",
        "path": "codex-rs/hepta-bellman-operator/src/profiles.rs",
        "old": (
            '        let mut bytes = b"hepta.learning-operator.world-model-profile.v1\\0".to_vec();\n'
            "        bytes.extend_from_slice(objective_digest.as_array());\n"
            "        bytes.extend_from_slice(sensor_core_digest.as_array());\n"
        ),
        "new": (
            '        let mut bytes = b"hepta.learning-operator.world-model-profile.v1\\0".to_vec();\n'
            "        bytes.extend_from_slice(objective_digest.as_array());\n"
            "        // MUTANT: sensor identity omitted from world-model profile.\n"
        ),
        "test": "world_model_profile_digest_binds_sensor_core_identity",
    },
    {
        "name": "disable-cooperative-cancellation",
        "path": "codex-rs/hepta-bellman-operator/src/budget.rs",
        "replacements": (
            ("        if context.control.is_cancelled() {\n", "        if false {\n"),
            (
                "        if self.context.control.is_cancelled() {\n",
                "        if false {\n",
            ),
        ),
        "test": "mutation_cancelled_work_is_rejected_before_fit",
    },
    {
        "name": "reset-matching-final-use-fit-context",
        "path": "codex-rs/hepta-bellman-operator/src/budget.rs",
        "old": (
            "        .is_some_and(|context| "
            "context.control.shares_cancellation_domain(control))\n"
        ),
        "new": "        .is_some_and(|_| false)\n",
        "test": "matching_work_control_preserves_capability_issue_time",
    },
    {
        "name": "collapse-full-input-candidate-digest",
        "path": "codex-rs/hepta-bellman-operator/src/sensor_core_qualification.rs",
        "old": (
            "    Ok(Digest32::of_bytes(&bytes))\n"
            "}\n\n"
            "fn validate_full_input_geometry(\n"
        ),
        "new": ("    Ok(Digest32::ZERO)\n}\n\nfn validate_full_input_geometry(\n"),
        "test": "full_input_digest_is_order_independent_and_content_sensitive",
    },
    {
        "name": "validate-only-selected-sensor-geometry",
        "path": "codex-rs/hepta-bellman-operator/src/sensor_core_qualification.rs",
        "old": ("        &all_candidates,\n        &build.manifest.selected_points,\n"),
        "new": (
            "        &build.manifest.selected_points,\n"
            "        &build.manifest.selected_points,\n"
        ),
        "test": "semantic_receipt_reports_exact_and_reduced_modes",
    },
    {
        "name": "relax-exclusive-final-use-deadline",
        "path": "codex-rs/hepta-bellman-operator/src/final_use_hardening.rs",
        "replacements": (
            (
                "    if issued_at_unix_micros >= absolute_deadline_unix_micros\n",
                "    if issued_at_unix_micros > absolute_deadline_unix_micros\n",
            ),
            (
                "        || use_observed_at_unix_micros >= absolute_deadline_unix_micros\n",
                "        || use_observed_at_unix_micros > absolute_deadline_unix_micros\n",
            ),
            (
                "        || publish_observed_at_unix_micros >= absolute_deadline_unix_micros\n",
                "        || publish_observed_at_unix_micros > absolute_deadline_unix_micros\n",
            ),
        ),
        "test": "capability_issue_at_deadline_fails_closed",
    },
    {
        "name": "disable-final-use-issuance-clock-fence",
        "path": "codex-rs/hepta-bellman-operator/src/final_use_hardening.rs",
        "old": "    if use_observed_at_unix_micros < issued_at_unix_micros\n",
        "new": "    if false\n",
        "test": "use_before_capability_issue_is_clock_regression",
    },
)


def run(
    command: list[str], *, cwd: Path, env: dict[str, str], timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout_seconds,
    )


def mutate(path: Path, mutant: dict[str, object]) -> None:
    text = path.read_text(encoding="utf-8")
    replacements = mutant.get("replacements")
    if replacements is None:
        replacements = ((mutant["old"], mutant["new"]),)
    for old, new in replacements:
        if text.count(old) != 1:
            raise RuntimeError(
                f"{mutant['name']}: expected exactly one mutation anchor in {path}"
            )
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def classify_test_result(
    completed: subprocess.CompletedProcess[str], junit: Path, target: str
) -> tuple[str, str]:
    """Accept one actual named test result; runner failures are inconclusive."""
    try:
        document = ET.parse(junit).getroot()
    except (OSError, ET.ParseError) as error:
        return "invalid", f"missing or malformed fresh JUnit report: {error}"
    cases = list(document.iter("testcase"))
    if len(cases) != 1:
        return "invalid", f"expected exactly one executed test, observed {len(cases)}"
    case = cases[0]
    name = case.get("name", "")
    if name.rsplit("::", 1)[-1] != target:
        return "invalid", f"JUnit reported a different target: {name!r}"
    if case.find("skipped") is not None or case.find("error") is not None:
        return "invalid", "target was skipped or had a runner/execution error"
    for suite in document.iter("testsuite"):
        if suite.get("errors", "0") != "0":
            return "invalid", "JUnit contains execution errors"

    summaries = re.findall(
        r"^\s*Summary\s+\[[^\]\n]+\]\s+(\d+) tests? run:\s*(.+)$",
        completed.stdout,
        re.MULTILINE,
    )
    if len(summaries) != 1 or summaries[0][0] != "1":
        return "invalid", "runner did not confirm exactly one executed test"
    counts = {
        metric: int(count)
        for count, metric in re.findall(
            r"(\d+) (passed|failed|skipped)", summaries[0][1]
        )
    }
    if re.search(
        r"timeout|timed out|exec fail|leak|abort|cancel", summaries[0][1], re.IGNORECASE
    ):
        return "invalid", "runner summary contains a non-assertion failure"

    failures = case.findall("failure")
    expected_status = "FAIL" if failures else "PASS"
    statuses = re.findall(
        rf"^\s*{expected_status}\s+\[[^\]\n]+\]\s+\S+\s+(\S+)\s*$",
        completed.stdout,
        re.MULTILINE,
    )
    if not any(test.rsplit("::", 1)[-1] == target for test in statuses):
        return "invalid", f"runner did not confirm a target {expected_status}"
    if not failures:
        if (
            completed.returncode == 0
            and counts.get("passed") == 1
            and counts.get("failed", 0) == 0
        ):
            return "passed", "target completed successfully"
        return "invalid", "successful JUnit case disagrees with process or summary"
    if len(failures) != 1 or completed.returncode == 0:
        return "invalid", "failure report disagrees with the process outcome"
    if counts.get("passed") != 0 or counts.get("failed") != 1:
        return "invalid", "runner did not confirm one failed target"
    failure = failures[0]
    # The message contains arbitrary test names and assertion text. Only the
    # pinned nextest execution type distinguishes a Rust test panic from a
    # timeout, crash, or other runner failure.
    disposition = failure.get("type", "")
    if disposition != "test failure with exit code 101":
        return "invalid", f"target did not fail by assertion: {disposition}"
    captured = "\n".join(case.itertext())
    panics = re.findall(
        r"thread ['\"]([^'\"]+)['\"](?:\s+\([^)]*\))?\s+panicked at",
        captured,
    )
    if not any(test.rsplit("::", 1)[-1] == target for test in panics):
        return "invalid", "JUnit does not contain the named target's Rust panic"
    return "failed", "named target failed with a recorded Rust panic"


def execute_target(
    *,
    worktree: Path,
    run_directory: Path,
    run_id: str,
    target: str,
    env: dict[str, str],
    timeout_seconds: int,
) -> dict[str, object]:
    run_directory.mkdir(parents=True, exist_ok=True)
    junit = run_directory / f"{run_id}.xml"
    log = run_directory / f"{run_id}.log"
    configuration = run_directory / f"{run_id}.toml"
    # A unique fresh path prevents a compiler/tool failure from reusing an old
    # passing or failing test report. The mutation profile has explicit limits;
    # it does not rely on the unsupported profile.inherits setting.
    junit.unlink(missing_ok=True)
    source_config = (worktree / "codex-rs/.config/nextest.toml").read_text(
        encoding="utf-8"
    )
    configuration.write_text(
        source_config + f"\n[profile.{MUTATION_PROFILE}]\n"
        'slow-timeout = { period = "30s", terminate-after = 2 }\n'
        "retries = 0\n"
        f"\n[profile.{MUTATION_PROFILE}.junit]\n"
        f"path = {json.dumps(str(junit))}\n"
        "store-success-output = false\nstore-failure-output = true\n",
        encoding="utf-8",
    )
    command = [
        "just",
        "--justfile",
        str(worktree / "justfile"),
        "test",
        "--locked",
        "-p",
        "codex-hepta-bellman-operator",
        "--features",
        "qualification-unverified-input",
        target,
        "--test-threads=1",
        "--retries=0",
        "--no-tests=fail",
        "--profile",
        MUTATION_PROFILE,
        "--config-file",
        str(configuration),
        "--color=never",
        "--status-level=all",
        "--final-status-level=fail",
        "--failure-output=final",
        "--success-output=never",
        "--hide-progress-bar",
    ]
    try:
        completed = run(command, cwd=worktree, env=env, timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        partial = error.stdout or b""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        log.write_text(partial, encoding="utf-8")
        raise RuntimeError(
            f"{run_id}: runner timed out; result is invalid, see {log}"
        ) from error
    log.write_text(completed.stdout, encoding="utf-8")
    outcome, reason = classify_test_result(completed, junit, target)
    record: dict[str, object] = {
        "outcome": outcome,
        "reason": reason,
        "returnCode": completed.returncode,
        "outputSha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "outputPath": str(log),
    }
    if junit.is_file():
        record["junitSha256"] = hashlib.sha256(junit.read_bytes()).hexdigest()
        record["junitPath"] = str(junit)
    return record


def write_report(
    output: Path,
    source_sha: str,
    results: list[dict[str, object]],
    baselines: list[dict[str, object]],
    status: str,
    error: str | None = None,
) -> None:
    report = {
        "schema": "hepta.learning-operator.mutation.v2",
        "schemaVersion": 2,
        "module": "learning.operator",
        "sourceSha": source_sha,
        "status": status,
        "runner": "just-nextest-junit",
        "baselines": baselines,
        "mutants": results,
        "killed": sum(result["status"] == "killed" for result in results),
        "survived": sum(result["status"] == "survived" for result in results),
    }
    if error is not None:
        report["error"] = error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default=".hepta-evidence/learning-operator/mutation.json"
    )
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    output_path = (ROOT / args.output).resolve()
    run_directory = output_path.parent / f"{output_path.stem}-runs" / source_sha
    target_directory = os.environ.get("CARGO_TARGET_DIR", str(ROOT / "target/mutation"))
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(Path(target_directory).resolve())
    env["CARGO_TERM_COLOR"] = "never"
    results: list[dict[str, object]] = []
    baselines: list[dict[str, object]] = []
    verified_targets: set[str] = set()
    # Clear any previous pass before work starts, including runs that later fail
    # to launch, compile, identify a test, or satisfy the watchdog.
    write_report(output_path, source_sha, results, baselines, "running")
    try:
        with tempfile.TemporaryDirectory(
            prefix="hepta-learning-operator-mutants-"
        ) as raw:
            worktree = Path(raw) / "source"
            subprocess.run(
                ["git", "worktree", "add", "--detach", str(worktree), source_sha],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                for mutant in MUTANTS:
                    subprocess.run(
                        ["git", "reset", "--hard", source_sha],
                        cwd=worktree,
                        check=True,
                        stdout=subprocess.DEVNULL,
                    )
                    target = str(mutant["test"])
                    if target not in verified_targets:
                        baseline = execute_target(
                            worktree=worktree,
                            run_directory=run_directory,
                            run_id=f"baseline-{target}",
                            target=target,
                            env=env,
                            timeout_seconds=args.timeout_seconds,
                        )
                        baselines.append({"test": target, **baseline})
                        if baseline["outcome"] != "passed":
                            raise RuntimeError(
                                f"{target}: unmutated baseline was not a confirmed pass: {baseline}"
                            )
                        verified_targets.add(target)
                    mutate(worktree / str(mutant["path"]), mutant)
                    observed = execute_target(
                        worktree=worktree,
                        run_directory=run_directory,
                        run_id=str(mutant["name"]),
                        target=target,
                        env=env,
                        timeout_seconds=args.timeout_seconds,
                    )
                    outcome = observed["outcome"]
                    status = (
                        "killed"
                        if outcome == "failed"
                        else "survived"
                        if outcome == "passed"
                        else "invalid"
                    )
                    result = {
                        "name": mutant["name"],
                        "path": mutant["path"],
                        "test": target,
                        "status": status,
                        **observed,
                    }
                    results.append(result)
                    if status != "killed":
                        raise RuntimeError(
                            f"{mutant['name']}: mutant {status}: {observed}"
                        )
                    write_report(output_path, source_sha, results, baselines, "running")
                    print(f"killed mutation: {mutant['name']}", flush=True)
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree)],
                    cwd=ROOT,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                shutil.rmtree(worktree, ignore_errors=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        write_report(output_path, source_sha, results, baselines, "fail", str(error))
        raise
    write_report(output_path, source_sha, results, baselines, "pass")


if __name__ == "__main__":
    main()
