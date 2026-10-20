"""Read-only audit of an interrupted real frozen Reader, never a full result.

Durably journaled prefix rows are genuine observations, but the remaining calls
are unknown. This tool neither runs a model nor issues production qualification.
"""

import argparse
import json
import math
from pathlib import Path
import statistics
from reader_reference import MODELS, PINS
from stage1_reader_score import answer_scores
from stage1_reader_pair import (
    digest,
    insist,
    read_json,
    records_from_run,
    strict_json,
    verify_inventory,
)

GENERATING_SOURCE = "5c9acdb340975adc2d16927fdb744023bd973bd8"
GENERATING_RUN = 39007522955
MAX_NEW_TOKENS = 64


def score_original(row, labels):
    item = labels[row["question_id"]]
    answer = item["answer"]
    return answer_scores(
        row["answer"], (answer,) if answer is not None else None, item["unanswerable"]
    )


def evaluate_prefix(plan, partial, original, labels, *, reference_identity):
    cases = plan["cases"]
    expected = [
        (case["question"]["identity"], arm)
        for case in cases
        for arm in case["conditions"]
    ]
    insist(
        len(cases) == 8 and len(expected) == len(set(expected)), "duplicate frozen plan"
    )
    insist(0 < len(partial) <= len(expected), "empty or oversized durable prefix")
    insist(set(original) == set(expected), "incomplete frozen baseline")
    lookup = {case["question"]["identity"]: case for case in cases}
    known_sum, compared = 0.0, 0
    rows, durations = [], []
    for index, row in enumerate(partial):
        insist(isinstance(row, dict), "original journal row must be an object")
        key = (row.get("question_id"), row.get("arm"))
        insist(
            key == expected[index], "partial journal not an untouched original prefix"
        )
        case, baseline = lookup[key[0]], original[key]
        insist(
            row.get("family") == case["family"] == baseline["family"]
            and row.get("phase") == case["phase"] == baseline["phase"]
            and row.get("status") in ("succeeded", "unavailable", "failed"),
            "case family, phase or actual attempt status drift",
        )
        result = {
            "question_id": key[0],
            "arm": key[1],
            "status": row["status"],
            "baseline_status": baseline["status"],
            "reference_answer_sha256": None,
            "baseline_answer_sha256": None,
            "source_bytes_matched": None,
            "diagnostic_f1_delta": None,
        }
        if row["status"] == "succeeded":
            receipt = row["receipt"]
            seconds, tokens = receipt["seconds"], receipt["generated_tokens"]
            insist(
                receipt["reader_identity"] == reference_identity
                and receipt["trainable_parameters"] == 0
                and receipt["answer_postprocessed"] is False
                and isinstance(row.get("answer"), str)
                and bool(row["answer"])
                and type(tokens) is int
                and 0 < tokens <= MAX_NEW_TOKENS
                and type(seconds) in (int, float)
                and math.isfinite(seconds)
                and 0 < seconds < 86400,
                "unattested or nonfinite actual reference inference",
            )
            insist(
                receipt["delivered_evidence"]
                == case["conditions"][key[1]]["delivered_evidence"],
                "delivered evidence differs from frozen source selection",
            )
            result["reference_answer_sha256"] = digest(row["answer"].encode())
            durations.append(seconds)
            if baseline["status"] == "succeeded":
                insist(
                    receipt["delivered_evidence"]
                    == baseline["receipt"]["delivered_evidence"],
                    "reference reader received different original evidence",
                )
                score_a, score_b = (
                    score_original(baseline, labels),
                    score_original(row, labels),
                )
                insist(
                    score_a["f1"] == baseline["f1"]
                    and score_a["exact_match"] == baseline["exact_match"],
                    "original baseline scorer drift",
                )
                result["source_bytes_matched"] = True
                result["baseline_answer_sha256"] = digest(baseline["answer"].encode())
                result["diagnostic_f1_delta"] = score_b["f1"] - score_a["f1"]
                known_sum += result["diagnostic_f1_delta"]
                compared += 1
        else:
            insist(
                not row.get("answer") and "receipt" not in row,
                "unexecuted model answer",
            )
        rows.append(result)
    total, unknown = len(expected), len(expected) - compared
    return {
        "planned": total,
        "durable_prefix": len(partial),
        "not_attempted": total - len(partial),
        "actual_successes": sum(r["status"] == "succeeded" for r in partial),
        "actual_unavailable": sum(r["status"] == "unavailable" for r in partial),
        "actual_failures": sum(r["status"] == "failed" for r in partial),
        "actually_paired": compared,
        "unpaired_or_not_attempted": unknown,
        "paired_observed_diagnostic_f1_delta": known_sum / compared
        if compared
        else None,
        "full_planned_delta_lower_bound": (known_sum - unknown) / total,
        "full_planned_delta_upper_bound": (known_sum + unknown) / total,
        "inference_seconds_observed": sum(durations),
        "inference_seconds_median": statistics.median(durations) if durations else None,
        "conditional_remaining_seconds_at_recorded_mean": (
            (total - len(partial)) * statistics.mean(durations) if durations else None
        ),
        "conditional_runtime_projection_not_measurement": True,
        "missing_outcome_bounds_not_statistical_intervals": True,
        "source_family_independence_established": False,
        "capacity_superiority_established": False,
        "parametric_memory_gain_established": False,
        "production_accepted": False,
        "rows": rows,
    }


def audit(root, labels_path, *, expected_source=GENERATING_SOURCE):
    root = Path(root)
    small, large = (
        root / "memory-stage1-real-smol-135m",
        root / "memory-stage1-real-smol-1.7b",
    )
    original, small_meta, frozen_plan = records_from_run(
        small, tier="smol-135m", expected_source=expected_source
    )
    inventory = verify_inventory(large)
    insist(
        (large / "tested-commit.txt").read_text().strip() == expected_source,
        "source drift",
    )
    stage, model = read_json(large / "stage.json"), read_json(large / "inventory.json")
    registration = read_json(large / "run/preregistered.json")
    execution = read_json(large / "run/diagnostic/execution/execution.json")
    own_plan = read_json(large / "run/diagnostic/reviewed-plan.json")
    insist(own_plan == frozen_plan, "actual Reader tasks or inputs changed")
    insist(
        (stage["tier"], stage["repository"], stage["revision"])
        == ("smol-1.7b", *MODELS["smol-1.7b"])
        and model["inventory_digest"] != small_meta["inventory_digest"]
        and stage["inventory_sha256"] == digest((large / "inventory.json").read_bytes())
        and stage["publisher_sha256"] == digest((large / "publisher.json").read_bytes())
        and registration["source_commit"] == expected_source
        and registration["input_pins"]
        == PINS | {"inventory": stage["inventory_sha256"]}
        and registration["optimization_permitted"] is False
        and execution["tested_commit"] == expected_source
        and execution["labels_sha256"] == PINS["labels"]
        and execution["reader_identity"] == model["inventory_digest"],
        "partial model revision, source, dataset or no-training contract mismatch",
    )
    labels_path = Path(labels_path)
    insist(
        labels_path.is_file() and not labels_path.is_symlink(), "regular label source"
    )
    label_bytes = labels_path.read_bytes()
    insist(
        digest(label_bytes) == PINS["labels"], "historical original answer pin drift"
    )
    labels = strict_json(label_bytes)
    expected_ids = {case["question"]["identity"] for case in frozen_plan["cases"]}
    insist(set(labels) == expected_ids, "missing, replaced or extra answer labels")
    journal_path = large / "run/diagnostic/execution/raw-answers.jsonl"
    insist(journal_path.is_file() and not journal_path.is_symlink(), "regular journal")
    journal = journal_path.read_bytes()
    insist(
        journal.endswith(b"\n") and len(journal) < 64 * 1024 * 1024, "truncated journal"
    )
    original_rows = [strict_json(line) for line in journal.splitlines()]
    result = evaluate_prefix(
        frozen_plan,
        original_rows,
        original,
        labels,
        reference_identity=model["inventory_digest"],
    )
    return {
        "schema": "hepta.memory.stage1.cancelled-prefix-review.v1",
        "original_generating_source": expected_source,
        "generating_workflow_run": GENERATING_RUN,
        "frozen_plan_sha256": digest(
            (large / "run/diagnostic/reviewed-plan.json").read_bytes()
        ),
        "original_partial_journal_sha256": digest(journal),
        "partial_artifact_inner_files_verified": len(inventory),
        "base_original_source": small_meta,
        "reference_model": {
            "revision": stage["revision"],
            "inventory_digest": model["inventory_digest"],
            "model_file_bytes": stage["model_file_bytes"],
            "staging_seconds": stage["seconds"],
        },
        "cancelled_run_status_must_be_verified_externally": True,
        "complete_original_reader_execution": False,
        "semantic_review_authenticated": False,
        **result,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source", default=GENERATING_SOURCE)
    args = parser.parse_args()
    result = audit(args.root, args.labels, expected_source=args.source)
    target = Path(args.output)
    insist(not target.exists(), "refuse to overwrite audit")
    target.write_text(
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )


if __name__ == "__main__":
    main()
