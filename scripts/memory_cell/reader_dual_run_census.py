"""Separate two source-pinned original Reader generating runs without pooling calls.

This consumes independent GitHub outer-ZIP audits and frozen task/answer audits.
No model calls, answer scoring, human review, or production admission.
"""

import argparse
import json
from pathlib import Path

from reader_external_artifact_audit import COHORTS

SCHEMA = "hepta.memory-cell.reader-dual-generating-run-census.v1"
ORIGINAL = 38538369649
REPAIRED = 38548446903
OUTER_SCHEMA = "hepta.memory-cell.reader-external-artifact-audit.v1"
BOUND_SCHEMA = "hepta.memory-cell.reader-source-bound-original-receipts.v1"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
SOURCE_ZIP_SHA = "31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a"
TIERS = ("smol-1.7b", "qwen-3b")


def checked_run(outer, bound, *, run_id):
    """One source's externally signed artifacts must reconcile one-for-one."""
    source, branch = COHORTS[run_id]
    if (
        outer.get("schema") != OUTER_SCHEMA
        or bound.get("schema") != BOUND_SCHEMA
        or outer.get("generating_source_commit") != source
        or bound.get("original_generating_commit") != source
        or outer.get("generating_run_id") != run_id
        or bound.get("original_run_id") != run_id
        or outer.get("expected_original_model_calls") != 80
        or outer.get("github_outer_zip_sha256_verified") is not True
        or outer.get("all_original_inner_sha256sums_verified") is not True
        or outer.get("original_run_and_source_bound") is not True
        or bound.get("frozen_plan_sha256") != PLAN_SHA
        or bound.get("frozen_source_zip_sha256") != SOURCE_ZIP_SHA
        or bound.get("original_ground_truth_parsed") is not False
        or outer.get("new_model_calls_by_this_audit") != 0
        or bound.get("new_model_calls") != 0
        or outer.get("production_accepted") is not False
        or bound.get("production_accepted") is not False
        or outer.get("original_model_task_score") is not None
        or outer.get("parametric_learning_gain") is not None
        or bound.get("reader_capacity_effect") is not None
        or bound.get("learned_memory_gain_proven") is not False
        or bound.get("independent_sufficiency_review") is not False
    ):
        raise ValueError("unqualified or mixed original Reader cohort attestation")
    shards = outer.get("shards")
    source_rows = bound.get("source_bindings")
    if (
        not isinstance(shards, list)
        or not isinstance(source_rows, list)
        or len(shards) != len(source_rows)
        or len(shards) != outer.get("github_artifact_count")
        or len(shards) != bound.get("github_qualified_artifact_count")
        or not 0 <= len(shards) <= 16
        or outer.get("absent_artifact_count") != 16 - len(shards)
    ):
        raise ValueError("incorrect source-cohort artifact census")
    by_id = {}
    for item in source_rows:
        ident = item.get("artifact_id")
        if type(ident) is not int or ident <= 0 or ident in by_id:
            raise ValueError("duplicated source-bound original ZIP identity")
        by_id[ident] = item
    assigned = set()
    for item in shards:
        ident = item.get("artifact_id")
        linked = by_id.get(ident)
        tier, index = item.get("tier"), item.get("case_index")
        if (
            linked is None
            or (tier, index) in assigned
            or tier not in TIERS
            or type(index) is not int
            or not 0 <= index < 8
            or item.get("artifact_name")
            != f"memory-reader-bottleneck-{tier}-{index}"
            or linked.get("tier") != tier
            or linked.get("case_index") != index
            or linked.get("github_zip_sha256") != item.get("github_zip_sha256")
            or linked.get("rows") != item.get("raw_attempt_rows")
            or linked.get("succeeded") != item.get("raw_success_rows")
            or linked.get("full_original_pair") != item.get("full_original_journal")
            or type(linked.get("exact_source_bound")) is not bool
            or not 0 <= linked["succeeded"] <= linked["rows"] <= 5
        ):
            raise ValueError("cross-run artifact or frozen evidence binding drift")
        assigned.add((tier, index))
    attempts = sum(row["rows"] for row in source_rows)
    successes = sum(row["succeeded"] for row in source_rows)
    full = sum(row["full_original_pair"] for row in source_rows)
    if (
        attempts != outer.get("original_attempt_rows")
        or attempts != bound.get("original_attempt_rows")
        or successes != outer.get("original_succeeded_generation_rows")
        or successes != bound.get("source_bound_successful_generations")
        or full != outer.get("completed_original_journal_shards")
        or full != bound.get("complete_five_arm_shards")
        or full > len(source_rows)
        or bound.get("eligible_source_bound_shards")
        != sum(item["exact_source_bound"] for item in source_rows)
    ):
        raise ValueError("Reader generation/cost census does not reconcile")
    return dict(
        generating_run_id=run_id,
        generating_source_commit=source,
        generating_branch=branch,
        original_shard_artifacts=len(shards),
        missing_shards=16 - len(shards),
        observed_original_attempts=attempts,
        successful_original_generations=successes,
        completed_five_arm_shards=full,
        source_bound_shards=bound["eligible_source_bound_shards"],
        dispositions=outer.get("dispositions"),
        learned_parameters_gain=None,
        human_reviewed_sufficiency=False,
        production_accepted=False,
    )


def reconcile(original_outer, original_bound, repaired_outer, repaired_bound):
    first = checked_run(original_outer, original_bound, run_id=ORIGINAL)
    second = checked_run(repaired_outer, repaired_bound, run_id=REPAIRED)
    if first["generating_source_commit"] == second["generating_source_commit"]:
        raise ValueError("source commits must not be identical")
    return dict(
        schema=SCHEMA,
        original=first,
        repaired=second,
        distinct_original_experiment_denominators=True,
        concatenate_original_answer_journals=False,
        cross_commit_pairwise_model_task_scores=None,
        trained_memory_gain=None,
        independently_reviewed_sufficient_evidence=False,
        actual_new_model_calls_by_auditor=0,
        production_accepted=False,
    )


def read_json(path):
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < path.stat().st_size <= 1024 * 1024
    ):
        raise ValueError("missing or oversized original audit file")
    return json.loads(path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original_outer", type=Path)
    parser.add_argument("original_bound", type=Path)
    parser.add_argument("repaired_outer", type=Path)
    parser.add_argument("repaired_bound", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = reconcile(
        read_json(args.original_outer),
        read_json(args.original_bound),
        read_json(args.repaired_outer),
        read_json(args.repaired_bound),
    )
    with args.report.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(
        json.dumps(
            {
                "original": report["original"]["successful_original_generations"],
                "repaired": report["repaired"]["successful_original_generations"],
                "pooled_model_success": None,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
