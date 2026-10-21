"""Seal a stopped original run using execution metadata, without scoring answers."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import audit_memory112_observations as original_cost_audit


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(root, output, observed_exit_code):
    observer = root / "evaluation-observed"
    completion = json.loads((observer / "observer-completion.json").read_bytes())
    run = json.loads((observer / "observer-run.json").read_bytes())
    journal = observer / "calls.jsonl"
    if completion["call_journal_sha256"] != sha(journal):
        raise ValueError("completed observer journal identity changed")
    rows = [json.loads(line) for line in journal.read_bytes().splitlines()]
    raw_path = root / "evaluation/raw-answers.jsonl"
    # The original partial answer journal is only hashed and counted, never parsed.
    raw_count = len(raw_path.read_bytes().splitlines())
    if not 0 < len(rows) == raw_count == completion["observed_calls"] < 72:
        raise ValueError("expected a stopped, incomplete original evaluation")
    plan_path = root / "original/plan/plan.json"
    if sha(plan_path) != original_cost_audit.PLAN:
        raise ValueError("original plan identity changed")
    plan = json.loads(plan_path.read_bytes())
    expected = [
        (case["query"]["identity"], arm)
        for case in plan["cases"]
        for arm in original_cost_audit.EVALUATION_ARMS
    ]
    if [(row["question_id"], row["arm"]) for row in rows] != expected[: len(rows)]:
        raise ValueError("observed calls are not the original ordered plan prefix")
    if run["source_commit"] != original_cost_audit.SOURCE:
        raise ValueError("original frozen source changed")
    if run["original_host_stop_seconds"] != 180 or observed_exit_code != 1:
        raise ValueError("original bound or observed process exit changed")
    if any(row["receipt"]["seconds"] > 180 for row in rows[:-1]):
        raise ValueError("execution continued beyond an earlier bound failure")
    if rows[-1]["receipt"]["seconds"] <= 180:
        raise ValueError("last completed call did not violate the original bound")
    log_path = root / "evaluation-execution.log"
    final_error = log_path.read_text().splitlines()[-1]
    if not final_error.startswith("RuntimeError: slow frozen reader:"):
        raise ValueError("original failure does not match the resource bound")
    for name in ("report.json", "scored-answers.json"):
        if (root / "evaluation" / name).exists():
            raise ValueError("partial evaluation unexpectedly has a score/report")
    fields = (
        "call_ordinal",
        "question_id",
        "arm",
        "status",
        "started_at",
        "completed_at",
        "pid",
        "procfs_self_pid",
        "observed_call_seconds",
        "process_user_cpu_seconds",
        "process_system_cpu_seconds",
        "sampled_peak_rss_bytes",
        "cumulative_process_high_water_rss_bytes",
        "rss_sample_count",
        "rss_sample_interval_seconds",
        "torch_intra_op_threads",
        "torch_inter_op_threads",
        "device",
        "dtype",
        "model_training",
        "explicit_generation_arguments",
    )
    receipt_fields = (
        "reader_identity",
        "reader_profile",
        "input_tokens",
        "generated_tokens",
        "token_limit",
        "seconds",
        "input_ids_digest",
        "generated_ids_digest",
        "trainable_parameters",
        "answer_postprocessed",
    )
    calls = [
        {key: row[key] for key in fields}
        | {"receipt_metadata": {key: row["receipt"][key] for key in receipt_fields}}
        for row in rows
    ]
    files = [
        journal,
        raw_path,
        observer / "observer-completion.json",
        observer / "observer-run.json",
        log_path,
        plan_path,
        root / "calibration/frozen-policy.json",
        root / "CALIBRATION40_COST_JOIN_V2.json",
        root / "resource-observations.jsonl",
    ]
    cgroup_names = (
        "memory.max",
        "memory.current",
        "memory.peak",
        "memory.events",
        "memory.stat",
        "cpu.max",
        "cpu.stat",
    )
    result = {
        "schema": "hepta.memory112.bounded-stop.metadata.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sealer_sha256": sha(Path(__file__)),
        "planned_calibration_calls": 40,
        "completed_calibration_calls": 40,
        "planned_evaluation_calls": 72,
        "completed_evaluation_calls": len(rows),
        "total_completed_calls": 40 + len(rows),
        "unexecuted_evaluation_calls": 72 - len(rows),
        "observed_process_exit_code": observed_exit_code,
        "exit_code_source": "exec session 54740 final result, independently observed",
        "execution_status": "stopped_by_original_per_call_wall_time_bound",
        "original_error": final_error,
        "original_per_call_bound_seconds": 180,
        "generation_exceptions": sum(row["status"] != "succeeded" for row in rows),
        "observer_process_elapsed_seconds": (
            datetime.fromisoformat(completion["completed_at"])
            - datetime.fromisoformat(run["started_at"])
        ).total_seconds(),
        "completed_call_metadata": calls,
        "original_partial_answers_parsed": False,
        "partial_evaluation_answers_scored": False,
        "evaluation_quality_conclusion": None,
        "full_112_completed": False,
        "retries_or_replacement_calls": 0,
        "original_threshold_modified": False,
        "artifacts": {
            str(path.relative_to(root)): {
                "sha256": sha(path),
                "bytes": path.stat().st_size,
            }
            for path in files
        },
        "post_exit_cgroup_snapshot": {
            name: (Path("/sys/fs/cgroup") / name).read_text() for name in cgroup_names
        },
        "cgroup_peak_is_container_cumulative_not_this_model_alone": True,
        "observer_cost_includes_instrumentation": True,
        "temporary_execution_container": True,
        "dedicated_project_host_attested": False,
        "independent_holdout": False,
        "physical_flops": None,
        "energy_joules": None,
        "complete_lifecycle_cost": None,
        "mode": "SHADOW_ONLY",
        "authority": "DENY_ALL",
        "qualification": "NO_GO",
    }
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"output": str(output), "sha256": sha(output)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--observed-exit-code", required=True, type=int)
    args = parser.parse_args()
    seal(args.root, args.output, args.observed_exit_code)


if __name__ == "__main__":
    main()
