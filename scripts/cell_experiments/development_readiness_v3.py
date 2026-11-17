"""Run exposed repository development tasks with a frozen real predictor."""

import argparse
import json
from pathlib import Path
import sys
import time

try:
    import resource
except ImportError:
    resource = None

from . import coding_sft, data, repo_execution, repo_interaction_v3
from .circuit_readiness_v3 import provenance_groups
from .protocol_v3 import prepare_record, verify_reference


def usage():
    if resource is None:
        return {
            "parent_cpu_seconds": time.process_time(),
            "verifier_child_cpu_seconds": None,
            "parent_peak_rss_bytes": None,
        }
    parent = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "parent_cpu_seconds": parent.ru_utime + parent.ru_stime,
        "verifier_child_cpu_seconds": children.ru_utime + children.ru_stime,
        "parent_peak_rss_bytes": parent.ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
    }


def run(predictor, records, output, maximum=2):
    """References must have been rebound before this measured student execution."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for record in records:
        if record.get("exposure") != "development":
            raise ValueError("readiness accepts exposed development records only")
    if not records or len({r["task_id"] for r in records}) != len(records):
        raise ValueError("readiness requires nonempty distinct task identities")
    inventory = {
        p.name: coding_sft.file_hash(p)
        for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    freeze = {
        "schema": "hepta.development-readiness-freeze.v3",
        "created_at_ns": time.time_ns(),
        "model_digest": predictor.model_digest,
        "records_digest": data.digest(records),
        "source_inventory": inventory,
        "maximum_attempts": maximum,
        "exposure": "development",
        "future_task_evidence": False,
        "scientific_confirmation_qualified": False,
    }
    coding_sft.write_new(output / "FREEZE.json", freeze)
    coding_sft.write_new(output / "RECORDS.json", records)
    start, before = time.perf_counter(), usage()
    rows = []
    try:
        for index, record in enumerate(records):
            observed = repo_interaction_v3.attempts(
                predictor, record, output / str(index), maximum=maximum
            )
            observed["task_digest"] = data.digest(record)
            rows.append(observed)
            print(
                json.dumps(
                    {
                        "task_id": record["task_id"],
                        "success": observed["success"],
                        "first_attempt_success": observed["first_attempt_success"],
                        "attempts": len(observed["steps"]),
                    }
                ),
                flush=True,
            )
    except BaseException as error:
        coding_sft.write_new(
            output / "FAILED.json",
            {
                "error": repr(error),
                "completed_tasks": len(rows),
                "partial_rows": rows,
                "automatic_retry": False,
            },
        )
        raise
    after = usage()
    if inventory != {
        p.name: coding_sft.file_hash(p)
        for p in sorted(Path(__file__).parent.glob("*.py"))
    }:
        raise ValueError("executable source changed during readiness")
    steps = [step for row in rows for step in row["steps"]]
    summaries = [step["execution_summary"] for step in steps]
    first_failures = sum(not row["first_attempt_success"] for row in rows)
    feedback_retries = sum(len(row["steps"]) > 1 for row in rows)
    recovered = sum(row["success"] and not row["first_attempt_success"] for row in rows)
    missing_counts = sum(
        s["execution_performed"] and s["subject_call_count"] is None for s in summaries
    )
    measured_calls = sum(s["subject_call_count"] or 0 for s in summaries)
    admitted = sum(s["execution_performed"] for s in summaries)
    unknown_admission = sum(
        not s["execution_summary"]["execution_performed"]
        and s["verification"]["result"].get("reason") != "invalid_test_patch"
        for s in steps
    )
    aliases = provenance_groups(
        [
            {
                "task_id": r["task_id"],
                "lineage_id": r["lineage_id"],
                "observation_digest": data.digest(r["task"]["messages"]),
            }
            for r in records
        ]
    )
    groups = {}
    for row in rows:
        group = groups.setdefault(
            row["source_id"], {"tasks": 0, "successes": 0, "first_attempt_successes": 0}
        )
        group["tasks"] += 1
        group["successes"] += row["success"]
        group["first_attempt_successes"] += row["first_attempt_success"]
    report = {
        "schema": "hepta.development-readiness.v3",
        "model_digest": predictor.model_digest,
        "freeze_digest": data.digest(freeze),
        "rows": rows,
        "task_count": len(rows),
        "task_lineage_input_groups": len(aliases),
        "source_count": len(groups),
        "by_source": groups,
        "model_calls": len(steps),
        "format_admitted_attempts": admitted if not unknown_admission else None,
        "known_format_admitted_attempts": admitted,
        "format_admission_unknown_attempts": unknown_admission,
        "executed_attempts": sum(s["execution_performed"] for s in summaries),
        "completed_original_calls": measured_calls if not missing_counts else None,
        "completed_original_call_measured_subtotal": measured_calls,
        "completed_call_measurement_missing_attempts": missing_counts,
        "completed_call_measurement_complete": missing_counts == 0,
        "original_passed_attempts": sum(
            s["original_passed"] is True for s in summaries
        ),
        "business_passed_attempts": sum(s["verification"]["success"] for s in steps),
        "first_attempt_successes": sum(r["first_attempt_success"] for r in rows),
        "successful_tasks": sum(r["success"] for r in rows),
        "first_attempt_failures": first_failures,
        "recovery_opportunities": feedback_retries,
        "recovered_tasks": recovered,
        "recovery_opportunity_scope": "tasks with a real follow-up model call after feedback; invalid retry outputs remain failures",
        "feedback_retry_tasks_with_test_execution": sum(
            any(s["executed"] for s in r["steps"][1:]) for r in rows
        ),
        "recovery_rate": recovered / feedback_retries if feedback_retries else None,
        "status": "ACTION_EXECUTION_OBSERVED"
        if any(r["success"] for r in rows)
        else "NOT_READY",
        "cost": {
            "wall_seconds": time.perf_counter() - start,
            "parent_cpu_seconds": after["parent_cpu_seconds"]
            - before["parent_cpu_seconds"],
            "verifier_child_cpu_seconds": (
                after["verifier_child_cpu_seconds"]
                - before["verifier_child_cpu_seconds"]
                if before["verifier_child_cpu_seconds"] is not None
                and after["verifier_child_cpu_seconds"] is not None
                else None
            ),
            "parent_process_peak_rss_bytes": after["parent_peak_rss_bytes"],
            "input_tokens": sum(s["output"]["input_tokens"] for s in steps),
            "output_tokens": sum(s["output"]["output_tokens"] for s in steps),
            "model_calls": len(steps),
            "output_cap_hits": sum(
                s["output"].get("hit_output_limit", False) for s in steps
            ),
            "scope": "student generation and semantic verification; model load and reference rebinding excluded",
            "gpu_seconds": None,
            "energy_joules": None,
            "complete": False,
        },
        "independent_sample_increment": 0,
        "external_teacher_count_added": 0,
        "exposure": "development",
        "old_B_C_are_not_unseen": True,
        "scientific_confirmation_qualified": False,
        "native_cell_adoption": False,
    }
    report["receipt_sha256"] = data.digest(report)
    coding_sft.write_new(output / "READINESS.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--backend", choices=("smollm-v2", "causal-v3"), default="smollm-v2"
    )
    args = parser.parse_args()
    repo_execution.load_catalog()
    original = [
        json.loads(line)
        for line in args.records.read_text().splitlines()
        if line.strip()
    ]
    records = [verify_reference(prepare_record(record)) for record in original]
    manifest = json.loads(args.manifest.read_text())
    if args.backend == "smollm-v2":
        predictor = coding_sft.load_predictor(manifest, args.artifact_root)
    else:
        from .causal_probe_v3 import Predictor

        predictor = Predictor(manifest, args.artifact_root)
    try:
        report = run(predictor, records, args.output)
    finally:
        predictor.close()
    print(
        json.dumps({k: v for k, v in report.items() if k not in ("rows", "by_source")}),
        flush=True,
    )


if __name__ == "__main__":
    main()
