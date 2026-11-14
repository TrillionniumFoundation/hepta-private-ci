"""Frozen command postconditions; a retrieved label never counts as task success."""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from budget_ledger import digest
from budget_process import run_job
from cohort_contract import file_sha, retain, validate_seal
from model_budget import ledger_for
from workflow_records import direct_command


LINT_FILE = "experiments/multimodal_output_portfolio/v4/counterfactual_audit.py"
LINT_DIR = "experiments/multimodal_output_portfolio/v4"
TASK_IDS = (
    "task-head-clippy",
    "counterfactual-lint",
    "execution-lock",
    "media-false-green",
)


def action_argv(command, ruff, workspace):
    """Restricted direct argv, fixed tool identity, no shell or gate relaxation."""
    parsed = direct_command(command) if isinstance(command, str) else None
    if parsed is None:
        return None, "no_single_short_command"
    argv = parsed["argv"]
    if argv[:3] in (["python", "-m", "ruff"], ["python3", "-m", "ruff"]):
        argv = ["ruff"] + argv[3:]
    if not argv or argv[0] != "ruff" or len(argv) < 2 or argv[1] != "check":
        return None, "not_in_registered_task_tool_schema"
    allowed_flags = {"--fix", "--unsafe-fixes", "--no-cache"}
    for arg in argv[2:]:
        if arg.startswith("-"):
            if arg not in allowed_flags:
                return None, "unregistered_action_flag"
        else:
            path = Path(arg)
            if path.is_absolute() or not (workspace / path).resolve().is_relative_to(
                workspace.resolve()
            ):
                return None, "action_path_outside_original_fixture"
    return [str(ruff.resolve()), "check", "--no-cache"] + argv[2:], None


def gate(ledger, event, argv, directory, workspace):
    return run_job(
        ledger,
        event,
        "infer",
        argv=argv,
        directory=directory,
        task_cwd=workspace,
        timeout_ns=20 * 10**9,
        upper_bound=dict(
            wall_ns=21 * 10**9,
            cpu_ns=21 * 10**9,
            read_bytes=64 * 1024**2,
            write_bytes=2 * 1024**2,
        ),
        output_limit=1024**2,
    )


def evaluate(study, root, output, predictions, method):
    validate_seal(study)
    protocol = json.loads((study / "protocol.json").read_text())
    expected = protocol["task_fixture_files"]
    for relative, sha in expected.items():
        if file_sha(root / relative) != sha:
            raise ValueError("original task fixture or tool differs from registration")
    if set(predictions) != set(TASK_IDS):
        raise ValueError("all four natural tasks remain in the outcome denominator")
    output.mkdir(parents=True, exist_ok=False)
    retain(
        output / "predictions-frozen.json",
        dict(
            method=method,
            predictions=predictions,
            input_policy="source-only or original-log-only proposal; no gold action lookup",
        ),
    )
    ledger = ledger_for(
        output / "budget.sqlite3",
        method + "-task-execution",
        protocol,
        file_sha(study / "protocol.json"),
    )
    results = []
    for task in TASK_IDS:
        if task != "counterfactual-lint":
            results.append(
                dict(
                    task_id=task,
                    task_success=False,
                    status="original_execution_environment_not_reconstructed",
                    proposed_command=predictions[task],
                    gate_executed=False,
                    reason="Rust build/toolchain or original hosted missing-codec workflow requires a separate pinned task environment",
                )
            )
            continue
        workspace = output / "original-source"
        shutil.copytree(root / "task-fixtures/lint-original", workspace)
        ruff = root / "ruff-runtime/bin/ruff"
        check = [
            str(ruff.resolve()),
            "check",
            "--no-cache",
            str((workspace / LINT_FILE).resolve()),
        ]
        before = gate(ledger, "original-gate", check, output / "before", workspace)
        original_log = (output / "before/stdout.log").read_text()
        if (
            before["returncode"] == 0
            or "F401" not in original_log
            or "E731" not in original_log
        ):
            results.append(
                dict(
                    task_id=task,
                    task_success=False,
                    status="original_failure_not_reproduced",
                    gate_executed=True,
                    original_gate_returncode=before["returncode"],
                )
            )
            continue
        action, refusal = action_argv(predictions[task], ruff, workspace)
        action_result = None
        if action:
            action_result = gate(
                ledger, "proposed-action", action, output / "action", workspace
            )
        after = gate(ledger, "postcondition", check, output / "after", workspace)
        semantic = None
        if after["returncode"] == 0:
            semantic = gate(
                ledger,
                "original-tests",
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    str((workspace / LINT_DIR).resolve()),
                    "-v",
                ],
                output / "tests",
                workspace,
            )
        test_text = (output / "tests/stderr.log").read_text() if semantic else ""
        success = bool(
            action_result
            and after["returncode"] == 0
            and semantic
            and semantic["returncode"] == 0
            and "Ran 76 tests" in test_text
        )
        results.append(
            dict(
                task_id=task,
                task_success=success,
                status="verified_original_task_success"
                if success
                else "original_gate_still_fails_or_action_unavailable",
                gate_executed=True,
                original_gate_returncode=before["returncode"],
                postcondition_returncode=after["returncode"],
                action=action,
                action_refusal=refusal,
                action_returncode=action_result["returncode"]
                if action_result
                else None,
                original_tests_returncode=semantic["returncode"] if semantic else None,
                success_requires_original_76_test_gate=True,
            )
        )
    result = dict(
        method=method,
        results=results,
        verified_task_successes=sum(r["task_success"] for r in results),
        denominator=4,
        original_task_gates_executed=sum(r["gate_executed"] for r in results),
        available_gate_subset_accuracy_is_not_full_task_coverage=True,
        budget=ledger.snapshot(),
        final_repair_gold_read=False,
        full_end_to_end_cost_complete=False,
        unmetered=[
            "fixture copy bytes and time before gates",
            "test Python OS dependency closure",
        ],
    )
    retain(output / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("study", "root", "output", "predictions"):
        parser.add_argument("--" + field, type=Path, required=True)
    parser.add_argument("--method", required=True)
    args = parser.parse_args()
    os.environ["RAYON_NUM_THREADS"] = "1"
    print(
        json.dumps(
            evaluate(
                args.study,
                args.root,
                args.output,
                json.loads(args.predictions.read_text()),
                args.method,
            ),
            sort_keys=True,
        )
    )
