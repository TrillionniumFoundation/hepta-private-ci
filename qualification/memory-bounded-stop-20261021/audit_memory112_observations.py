"""Join complete original Memory journals to transparent per-call measurements.

This reads evaluation answers only after the original 72-call completion seal.
It never re-scores, repairs answers, changes the policy, or grants qualification.
"""

import argparse
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

SOURCE = "2f8c5678d19713ed4d532768f245a4810b139377"
IDENTITY = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
STAGE = "ceae3536947e7c84e5d55a8c93491654aa388c91961d504ccede6d5650785ba9"
POLICY = "21be6cf2d6346bf2283352e7f5cc92748db0f10d8df25add201809dc3b70726a"
PREP = "44516f3bf6a69b6e39deae7a61b17f612cc53749eb4753f7598b325cbc38bc04"
PLAN = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
EVALUATION_ARMS = (
    "selected_k",
    "hybrid_k4",
    "hybrid_k6",
    "hybrid_k4_reversed",
    "single_hop",
    "entity_time",
    "organized",
    "program_support",
    "empty",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path, expected=None):
    if expected is not None and sha(path) != expected:
        raise ValueError("sealed artifact identity differs: " + str(path))
    return json.loads(path.read_text())


def token_digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def audit_phase(root, phase):
    calibration = phase == "calibration"
    expected_calls = 40 if calibration else 72
    arms = tuple(f"k{k}" for k in (1, 2, 3, 4, 6)) if calibration else EVALUATION_ARMS
    observed = root / (
        "calibration-observed-attempt2" if calibration else "evaluation-observed"
    )
    output = root / phase
    completion = read(observed / "observer-completion.json")
    if completion["observed_calls"] != expected_calls:
        raise ValueError(
            "full planned completion seal required before answer inspection"
        )
    raw_path = output / "raw-answers.jsonl"
    journal_path = observed / "calls.jsonl"
    raw_lines = raw_path.read_text().splitlines()
    observer_lines = journal_path.read_text().splitlines()
    if len(raw_lines) != expected_calls or len(observer_lines) != expected_calls:
        raise ValueError("complete original and observed call journals required")
    if completion["call_journal_sha256"] != sha(journal_path):
        raise ValueError("observer journal differs from completion seal")
    run = read(observed / "observer-run.json")
    if run["source_commit"] != SOURCE or run["original_host_stop_seconds"] != 180:
        raise ValueError("original source or time budget changed")
    plan_path = root / (
        "prep/calibration-plan.json" if calibration else "original/plan/plan.json"
    )
    plan = read(plan_path, PREP if calibration else PLAN)
    expected = [case["query"]["identity"] for case in plan["cases"]]
    if len(expected) != 8 or len(set(expected)) != 8:
        raise ValueError("original eight-task population required")
    originals = [json.loads(line) for line in raw_lines]
    observations = [json.loads(line) for line in observer_lines]
    keys = [(row["question_id"], row["arm"]) for row in originals]
    if len(set(keys)) != expected_calls or set(keys) != {
        (question, arm) for question in expected for arm in arms
    }:
        raise ValueError("planned task/arm census mismatch")
    calls = []
    for index, (raw, observed_row) in enumerate(
        zip(originals, observations, strict=True), 1
    ):
        if (
            (observed_row["question_id"], observed_row["arm"]) != keys[index - 1]
            or observed_row["call_ordinal"] != index
            or raw["status"] != "succeeded"
            or observed_row["status"] != raw["status"]
        ):
            raise ValueError(
                "complete successful original-to-observer call pairing required"
            )
        receipt = raw["receipt"]
        inputs = observed_row["input_token_ids"]
        full_output = observed_row["complete_output_token_ids"]
        generated = full_output[len(inputs) :]
        if (
            full_output[: len(inputs)] != inputs
            or token_digest(inputs) != receipt["input_ids_digest"]
            or token_digest(generated) != receipt["generated_ids_digest"]
            or len(inputs) != receipt["input_tokens"]
            or len(generated) != receipt["generated_tokens"]
            or observed_row["raw_answer"] != raw["answer"]
            or observed_row["receipt"] != receipt
            or receipt["reader_identity"] != IDENTITY
            or observed_row["reader_identity"] != IDENTITY
            or receipt["token_limit"] != 2048
            or not 0 < len(inputs) <= 2048
            or not 0 < len(generated) <= 64
            or not 0 <= receipt["seconds"] <= 180
            or receipt["answer_postprocessed"] is not False
            or receipt["trainable_parameters"] != 0
        ):
            raise ValueError("original raw answer/token/identity/budget join failed")
        generation = observed_row["explicit_generation_arguments"]
        if (
            generation["max_new_tokens"] != 64
            or generation["do_sample"] is not False
            or generation["num_beams"] != 1
            or generation["use_cache"] is not True
            or observed_row["torch_intra_op_threads"] != 2
            or observed_row["model_training"] is not False
            or observed_row["dtype"] != "torch.bfloat16"
            or observed_row["device"] != "cpu"
        ):
            raise ValueError("fixed inference configuration changed")
        calls.append(
            {
                "ordinal": index,
                "question_id": raw["question_id"],
                "kind": raw["kind"],
                "arm": raw["arm"],
                "input_tokens": len(inputs),
                "generated_tokens": len(generated),
                "reader_seconds": receipt["seconds"],
                "observed_call_seconds": observed_row["observed_call_seconds"],
                "user_cpu_seconds": observed_row["process_user_cpu_seconds"],
                "system_cpu_seconds": observed_row["process_system_cpu_seconds"],
                "sampled_peak_rss_bytes": observed_row["sampled_peak_rss_bytes"],
                "cumulative_process_high_water_rss_bytes": observed_row[
                    "cumulative_process_high_water_rss_bytes"
                ],
                "input_ids_sha256": receipt["input_ids_digest"],
                "generated_ids_sha256": receipt["generated_ids_digest"],
            }
        )
    by_arm = {}
    for arm in arms:
        rows = [row for row in calls if row["arm"] == arm]
        times = sorted(row["observed_call_seconds"] for row in rows)
        by_arm[arm] = {
            "calls": len(rows),
            **{
                key: sum(row[key] for row in rows)
                for key in (
                    "input_tokens",
                    "generated_tokens",
                    "reader_seconds",
                    "observed_call_seconds",
                    "user_cpu_seconds",
                    "system_cpu_seconds",
                )
            },
            "p50_observed_call_seconds": statistics.median(times),
            "p95_observed_call_seconds": times[math.ceil(0.95 * len(times)) - 1],
            "maximum_sampled_process_rss_bytes": max(
                row["sampled_peak_rss_bytes"] for row in rows
            ),
        }
    report_path = output / "report.json"
    scored_path = output / "scored-answers.json"
    report = read(report_path) if report_path.exists() else None
    if scored_path.exists():
        scored = read(scored_path)
        if len(scored) != len(originals) or any(
            any(scored_row.get(key) != value for key, value in raw.items())
            for scored_row, raw in zip(scored, originals, strict=True)
        ):
            raise ValueError("original scorer changed generated answer/receipt fields")
    if report is not None:
        if (
            report["raw_answers_sha256"] != sha(raw_path)
            or report["source_commit"] != SOURCE
        ):
            raise ValueError("original report is detached from raw observations")
        summaries = report["arms" if calibration else "success_by_arm"]
        for arm, values in by_arm.items():
            summary = summaries[arm]
            if (
                values["input_tokens"] != summary["input_tokens"]
                or values["generated_tokens"] != summary["output_tokens"]
                or values["calls"] != summary["succeeded"]
                or abs(values["reader_seconds"] - summary["inference_seconds"]) > 1e-8
            ):
                raise ValueError("original report costs differ from raw measured calls")
    files = [
        raw_path,
        journal_path,
        observed / "observer-run.json",
        observed / "observer-completion.json",
        plan_path,
    ] + [path for path in (report_path, scored_path) if path.exists()]
    return {
        "phase": phase,
        "original_source_commit": SOURCE,
        "planned_calls": expected_calls,
        "completed_calls": len(calls),
        "original_report_issued": report is not None,
        "raw_answer_token_and_cost_joins_verified": True,
        "source_artifacts_sha256": {str(p.relative_to(root)): sha(p) for p in files},
        "source_artifacts_bytes": {
            str(p.relative_to(root)): p.stat().st_size for p in files
        },
        "elapsed_observer_process_seconds": (
            datetime.fromisoformat(completion["completed_at"])
            - datetime.fromisoformat(run["started_at"])
        ).total_seconds(),
        "per_arm_costs": by_arm,
        "per_call_costs": calls,
        "original_report": report,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--phase", choices=("calibration", "both"), default="both")
    args = parser.parse_args()
    policy = read(args.root / "calibration/frozen-policy.json", POLICY)
    if policy["selected_k"] != 1 or policy["stage_sha256"] != STAGE:
        raise ValueError("original frozen calibration policy changed")
    if (
        sha(args.root / "calibration/raw-answers.jsonl") != policy["raw_answers_sha256"]
        or sha(args.root / "calibration/scored-answers.json")
        != policy["scored_answers_sha256"]
    ):
        raise ValueError("calibration outputs differ from frozen policy identities")
    phases = (
        ("calibration",)
        if args.phase == "calibration"
        else ("calibration", "evaluation")
    )
    result = {
        "schema": "hepta.memory112.observed-cost-join.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "auditor_sha256": sha(Path(__file__)),
        "original_model_stage_sha256": STAGE,
        "original_frozen_policy_sha256": POLICY,
        "phase_audits": [audit_phase(args.root, phase) for phase in phases],
        "physical_flops": None,
        "energy_joules": None,
        "billed_cost": None,
        "complete_lifecycle_cost": None,
        "rss_is_sampled_whole_process_not_allocator_peak": True,
        "observer_included_in_process_cost": True,
        "prior_authored_exposed_development_replication": True,
        "independent_holdout": False,
        "independent_semantic_review": False,
        "mode": "SHADOW_ONLY",
        "authority": "DENY_ALL",
        "qualification": "NO_GO",
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"phases": list(phases), "output_sha256": sha(args.output)}))


if __name__ == "__main__":
    main()
