"""Separate scheduler lifecycle events from scientific worker attempts."""

import hashlib
import json
from pathlib import Path


def controller_history(results, executions, current_seals=None):
    root = Path(results)
    starts = []
    for path in sorted(root.glob("CONTROLLER_START_*.json")):
        number = int(path.stem.rsplit("_", 1)[1])
        starts.append((number, path, json.loads(path.read_text())))
    neural_starts = []
    for stage in ("mechanism", "representation", "scaling"):
        for path in (root / stage).rglob("START.json"):
            value = json.loads(path.read_text())
            if "spec" in value and "started_unix" in value:
                neural_starts.append(value)
    entries, issues = [], []
    for index, (number, start_path, start) in enumerate(starts):
        end = (
            starts[index + 1][2]["started_unix"]
            if index + 1 < len(starts)
            else float("inf")
        )
        assigned = [
            row
            for row in executions
            if start["started_unix"] <= row["started_unix"] < end
        ]
        observed_starts = [
            row
            for row in neural_starts
            if start["started_unix"] <= row["started_unix"] < end
        ]
        result_path = root / f"CONTROLLER_RESULT_{number:02d}.json"
        pause_path = root / f"CONTROLLER_PAUSE_{number:02d}.json"
        progress_path = root / f"CONTROLLER_PROGRESS_{number:02d}.json"
        entry = {
            "invocation": number,
            "start": start,
            "worker_attempts_with_receipts": len(assigned),
            "scientific_starts_observed": len(observed_starts),
            "worker_child_cpu_seconds": sum(
                row["child_cpu_seconds"]
                for row in assigned
                if row.get("child_cpu_seconds") is not None
            ),
            "worker_cumulative_wall_seconds": sum(
                row["wall_seconds"] for row in assigned
            ),
            "receipt_sha256": {
                start_path.name: hashlib.sha256(start_path.read_bytes()).hexdigest()
            },
        }
        if (
            current_seals is not None
            and (assigned or observed_starts)
            and start.get("source_seals") != current_seals
        ):
            issues.append(
                {
                    "invocation": number,
                    "issue": "controller with scientific jobs declared a different source seal",
                }
            )
        if result_path.exists():
            value = json.loads(result_path.read_text())
            entry.update(status="completed_controller_invocation", result=value)
            if value["execution_receipts"] != len(assigned):
                issues.append(
                    {
                        "invocation": number,
                        "issue": "controller result/worker receipt count mismatch",
                    }
                )
        elif pause_path.exists():
            value = json.loads(pause_path.read_text())
            declared_started, declared_done = (
                set(value["started_jobs"]),
                set(value["completed_jobs"]),
            )
            observed_started = {
                row["spec"]["id"]
                for row in neural_starts
                if row["started_unix"] <= value["time"]
            }
            successful = {
                row["id"]
                for row in executions
                if row["exit_code"] == 0
                and row["result_exists"]
                and row["ended_unix"] <= value["time"]
            }
            crossing = [
                row
                for row in executions
                if row["started_unix"] < value["time"] < row["ended_unix"]
            ]
            valid = (
                value["interrupted_scientific_jobs"] == 0
                and declared_started == declared_done
                and declared_started == observed_started
                and declared_done <= successful
                and not crossing
            )
            entry.update(
                status="paused_between_scientific_jobs"
                if valid
                else "pause_evidence_disagrees",
                pause=value,
                no_scientific_interruption_verified=valid,
            )
            if not valid:
                issues.append(
                    {
                        "invocation": number,
                        "issue": "declared between-job pause disagrees with START/execution evidence",
                    }
                )
            entry["receipt_sha256"][pause_path.name] = hashlib.sha256(
                pause_path.read_bytes()
            ).hexdigest()
        elif progress_path.exists():
            progress = json.loads(progress_path.read_text())
            no_work = (
                not assigned
                and not observed_starts
                and not progress["running"]
                and not progress["completed"]
                and progress["resource_wait"]
            )
            entry.update(
                status="prestart_resource_wait_without_normal_result"
                if no_work
                else "in_progress_or_unclosed",
                last_progress=progress,
            )
        else:
            entry["status"] = "no_completion_or_progress_receipt"
        if result_path.exists():
            entry["receipt_sha256"][result_path.name] = hashlib.sha256(
                result_path.read_bytes()
            ).hexdigest()
        if progress_path.exists():
            entry["receipt_sha256"][progress_path.name] = hashlib.sha256(
                progress_path.read_bytes()
            ).hexdigest()
        entries.append(entry)
    return {
        "invocations": entries,
        "issues": issues,
        "classification_scope": "controller exit codes and pauses are not scientific worker failures; worker failures are counted only from per-job execution receipts",
        "cost_scope": "worker CPU remains accounted by wait4 receipts across pauses; controller self-CPU and unrecorded controller wall overhead remain unknown, not zero",
    }
