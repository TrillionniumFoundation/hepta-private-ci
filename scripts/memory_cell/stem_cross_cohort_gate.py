"""Immutable cross-experiment gate: source coverage != Reader quality != learned gain.

Reads only three already-committed research JSON receipts, SHA-bound to their
Git blobs. No model, source text, private answer, hidden labels, or production
action. Repeated checkpoints/runs are NOT independent evaluation subjects.
"""

import argparse
import hashlib
import json
from pathlib import Path

PINS = {
    "locomo-ninearm-offline-20261012.json": "6b7592e000bf5e0569b47dc2bcce1ec5b5004717",
    "stem-two-run-negative-gate-20261011.json": "f86b66bfc580ca1bbea46ed10e70352b70fc1441",
    "strong-rag-four-run-replication-20261012.json": "04154def5466165e82d77c9a92d1ff70f6839177",
}
SCHEMAS = (
    "hepta.memorycell.locomo-nine-arm-independent-evaluation.v1",
    "hepta.memory-cell.stem-native-two-run-negative-gate.v1",
    "hepta.memory-strong-rag.four-original-runs.v1",
)
ARMS = tuple(f"{m}_k{k}" for m in ("lexical", "recent", "fusion") for k in (2, 4, 8))
LEARNED = (
    "prototype", "linear", "gated", "lineage_lora_gated",
    "independent_lora_gated",
)
RUNS = ("A", "B", "C", "D")


def require(value, reason):
    if not value:
        raise ValueError(reason)


def strict_json(data):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, "duplicate source receipt JSON property")
            result[k] = v
        return result

    def nonfinite(text):
        raise ValueError("nonfinite source receipt JSON constant: " + text)

    return json.loads(
        data, object_pairs_hook=unique, parse_constant=nonfinite
    )


def pinned_inputs(data_dir):
    root = Path(data_dir)
    require(root.is_dir() and not root.is_symlink(), "bounded regular input folder")
    result, receipt = {}, {}
    for name, sha in PINS.items():
        file = root / name
        require(
            file.parent.resolve() == root.resolve()
            and file.is_file() and not file.is_symlink()
            and 0 < file.stat().st_size < 65536,
            "regular, bounded, non-symlink pinned receipt required",
        )
        blob = file.read_bytes()
        actual = hashlib.sha1(
            b"blob " + str(len(blob)).encode() + bytes((0,)) + blob
        ).hexdigest()
        require(actual == sha, "pinned historical Git blob changed: " + name)
        result[name] = strict_json(blob)
        receipt[name] = dict(
            git_blob_sha1=actual,
            file_sha256=hashlib.sha256(blob).hexdigest(),
            bytes=len(blob),
        )
    return result, receipt


def audit_receipts(locomo, stem, rag):
    require(
        tuple(x["schema"] for x in (locomo, stem, rag)) == SCHEMAS,
        "unregistered historical evidence metric schema",
    )
    require(
        locomo["source_commit"] == "fcc24ad653700ad5f47f09350cf7815242dc5de8"
        and locomo["original_six_arm_replay_agrees"] is True
        and locomo["selected_arm"] == "lexical_k8"
        and locomo["models_generated"] == 0
        and locomo["evaluation_questions"] == 16
        and locomo["selection_families"] == locomo["tested_families"] == 2
        and locomo["independent_source_family_authentication"] is False
        and locomo["published_data_pretraining_contamination_unknown"] is True
        and locomo["citation_entailment_precision"] is None
        and locomo["production_accepted"] is False
        and set(locomo["selection"]) == set(locomo["evaluation"]) == set(ARMS),
        "LoCoMo source-recall provenance or policy separation changed",
    )
    for phase, eligible, unknown in (("selection", 10, 6), ("evaluation", 13, 3)):
        for arm, row in locomo[phase].items():
            families = row["per_family"]
            require(
                row["planned"] == 16
                and row["eligible"] == eligible
                and row["unknown_or_unanswerable"] == unknown
                and row["full_annotated_support_covered"] <= eligible
                and row["full_annotated_support_covered"] >= 0
                and row["selected_source_bytes"] > 0
                and len(families) == 2
                and sum(f["eligible"] for f in families.values()) == eligible
                and sum(f["covered"] for f in families.values())
                == row["full_annotated_support_covered"],
                "LoCoMo missing/duplicate family or source coverage denominator: "
                + phase + "/" + arm,
            )
    chosen = locomo["evaluation"]["lexical_k8"]
    short = locomo["evaluation"]["lexical_k4"]
    fusion = locomo["evaluation"]["fusion_k8"]
    require(
        chosen["full_annotated_support_covered"] == 9
        and short["full_annotated_support_covered"] == 8
        and fusion["full_annotated_support_covered"] == 3
        and chosen["selected_source_bytes"] == 17085
        and short["selected_source_bytes"] == 8636,
        "published fixed LoCoMo retrieval comparison changed",
    )
    require(
        len(stem["runs"]) == 2
        and all(
            run["status"] == "success"
            and run["logical_policy_attempts"] == 576
            and len(run["artifact_zip_sha256"]) == 64
            for run in stem["runs"]
        )
        and stem["exact_cross_run_replayed_policy_rows"] == 576
        and all(v == 0 for v in stem["cross_run_mismatches"].values())
        and stem["learned_arms"] == list(LEARNED)
        and stem["checkpoints"] == [16, 32, 48]
        and stem["test_and_transfer_unique_questions_per_checkpoint"] == 16
        and stem["test_and_transfer_repeated_stage_pairs_per_learned_arm"] == 48
        and stem["heldout_development_source_selection_wins_per_arm"] == 0
        and stem["heldout_development_answer_changes_per_arm"] == 0
        and stem["independently_authenticated_prospective_source_families"] == 0
        and stem["semantic_citation_precision_certified"] is False
        and stem["parametric_memory_advantage_established"] is False
        and stem["production_accepted"] is False,
        "original strict-six-arm repeats or learning verdict changed",
    )
    weak_reader = stem["second_run_test_transfer"]
    require(
        weak_reader["planned_count"] == 48
        and weak_reader["non_null_f1_count"] == 42
        and weak_reader["missing_f1_count"] == 6
        and weak_reader["answer_citation_markers_count"] == 0
        and weak_reader["all_five_learned_arms_same_observations"] is True,
        "Reader diagnostics or repeated-questions denominator changed",
    )
    require(
        rag["source_runs"] == 4
        and set(rag["chosen_k"]) == set(RUNS)
        and all(v == 1 for v in rag["chosen_k"].values())
        and rag["actual_archived_model_generations"] == 448
        and rag["original_generations_per_run"] == 112
        and rag["unchanged_input_prompt_census"] == {
            "calibration": 40, "evaluation": 72
        }
        and rag["independent_new_source_families"] == 0
        and rag["independent_semantic_citation_adjudication"] is False
        and rag["repeated_questions_are_independent"] is False
        and rag["org_task_accuracy_superiority"] is False
        and rag["org_complete_citation_superiority"] is False
        and rag["full_production_lifecycle_cost_measured"] is False
        and rag["production_accepted"] is False,
        "four-run authored Reader replication or its independence gate changed",
    )
    for run in RUNS:
        org = rag["per_arm"]["organized"][run]
        full = rag["per_arm"]["entity_time"][run]
        selected = rag["per_arm"]["selected_k"][run]
        require(
            (org["correct"], org["complete_declared_citation_chains"])
            == (8, 4)
            and (full["correct"], full["complete_declared_citation_chains"])
            == (8, 4)
            and (selected["correct"], selected["complete_declared_citation_chains"])
            == (5, 3)
            and org["input_tokens"] == 5179
            and full["input_tokens"] == 5752,
            "repeated authored Reader/citation result changed",
        )

    return {
        "schema": "hepta.memory-cell.cross-cohort-negative-admission.v1",
        "research_only": True,
        "independent_prospective_families": 0,
        "locomo": {
            "selected_pre_evaluation": "lexical_k8",
            "planned_evaluation_questions": 16,
            "native_support_evaluable_questions": 13,
            "source_coverage_selected": 9,
            "source_coverage_fixed_k4": 8,
            "source_coverage_fusion_k8": 3,
            "selected_source_utf8_bytes": 17085,
            "k4_source_utf8_bytes": 8636,
            "incremental_k8_minus_k4_source_utf8_bytes": 8449,
            "additional_native_covered_questions": 1,
            "evaluated_source_families": 2,
            "actual_reader_answers_tested": 0,
            "semantic_citation_precision": None,
        },
        "strict_native_stem": {
            "original_policy_executions_per_run": 576,
            "independent_runs": 2,
            "distinct_test_transfer_questions": 16,
            "repeated_test_transfer_pairs_per_arm": 48,
            "learned_arms_with_proven_test_transfer_gain": 0,
            "reader_answer_f1_within_declared_repeated_pairs": weak_reader[
                "mean_answer_token_f1_over_planned_count"
            ],
            "observed_answer_citation_markers": 0,
            "semantic_citation_precision": None,
        },
        "authored_strong_rag": {
            "same_eight_development_questions_repeated_runs": 4,
            "distinct_authored_evaluation_questions": 8,
            "correct_tasks_for_full_entity_path": 8,
            "correct_tasks_for_organized_path": 8,
            "complete_declared_citation_chain_both": 4,
            "independently_judged_citation_chains": 0,
            "additional_organized_task_or_declared_chain_gain": 0,
            "actual_per_request_production_tco_measured": False,
        },
        "do_not_pool_cross_benchmark_denominators": True,
        "no_go_reasons": [
            "No real held-out task gain for learned Stem Heads over frozen on 16 distinct test/transfer cases",
            "Only two LoCoMo evaluation source families and no prospective independence",
            "Reader authored answer success differs from complete declared citation-chain support",
            "No independent semantic citation adjudication and no full production-lifecycle cost",
        ],
        "development_priority": (
            "Verify frozen support coverage and independently reviewed Reader "
            "source entailment on new families before any Cell scale-out"
        ),
        "learned_cell_scale_out_authorized": False,
        "independent_semantic_precision_99_proven": False,
        "production_accepted": False,
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--data-dir", type=Path, default=Path(__file__).resolve().parent / "data"
    )
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    inputs, pins = pinned_inputs(args.data_dir)
    report = audit_receipts(
        inputs["locomo-ninearm-offline-20261012.json"],
        inputs["stem-two-run-negative-gate-20261011.json"],
        inputs["strong-rag-four-run-replication-20261012.json"],
    )
    report["immutable_input_sha256"] = pins
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
