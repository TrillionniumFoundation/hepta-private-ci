"""Immutable audit: train-only Head residual scaling vs actual held-out source loss.

Audit the original persisted score-only shadow decisions (NO Reader calls).
This is a negative-control/rejection receipt, NOT a hyperparameter search
over test labels and NOT a semantic source-entailment certificate.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from stem_audit_archive import PinnedArchive, require

SOURCE = "953c65d9cf9a79dbd3e6543e2177a6a6ef61ed9c"
TREE = "4c57c214109b756ff97415c1f235a7250e4b9a6f"
ZIP_SHA = "3fe286f84d7f719ebe9ee300d3772aec1842dafb5c97ab9dfdb792eb4daaf43c"
STAGES = (16, 32, 48)
ARMS = ("prototype", "linear", "gated", "lineage_lora_gated", "independent_lora_gated")
PHASES = ("select", "retention", "test", "transfer")
CELLS = ("general", "temporal")
SHADOW_GRID = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0)


def audit_shadow(plan, calibrations, decisions, provenance, postpolicy):
    cohorts = plan["questions"]
    routes = plan["routes"]
    require(
        tuple(plan["curriculum_attempted_examples"]) == STAGES
        and len(cohorts["train"]) == 48
        and all(len(cohorts[p]) == 8 for p in PHASES)
        and len({q for group in cohorts.values() for q in group}) == 80
        and set(routes) == {q for group in cohorts.values() for q in group}
        and all(route in CELLS for route in routes.values())
        and plan["source_visibility_policy"]
        == "strict-as-of-before-index-and-every-Encoder-v1",
        "registered cohort or as-of input identity changed",
    )
    expected_calibrations = {
        (stage, arm, cell) for stage in STAGES for arm in ARMS for cell in CELLS
    }
    by_fit = {}
    for row in calibrations:
        key = (row["stage"], row["arm"], row["cell"])
        receipt = row.get("receipt")
        require(
            key in expected_calibrations
            and key not in by_fit
            and row["status"] == "succeeded"
            and row["role"] == "nonqualifying-train-only-shadow-scale"
            and isinstance(receipt, dict)
            and tuple(receipt["scale_grid"]) == SHADOW_GRID
            and receipt["stage"] == key[0]
            and receipt["arm"] == key[1]
            and receipt["cell"] == key[2]
            and receipt["chosen_scale"] in SHADOW_GRID
            and receipt["winner_chosen_from_train_only"] is True
            and receipt["all_test_and_transfer_answers_and_labels_unseen"] is True
            and receipt["no_new_reader_call"] is True
            and receipt["production_accepted"] is False,
            "shadow scale not fitted entirely on admitted TRAIN source labels",
        )
        by_fit[key] = row
    require(set(by_fit) == expected_calibrations, "missing training-scale calibration")

    expected_choices = {
        (stage, phase, qid, arm)
        for stage in STAGES
        for arm in ARMS
        for phase in PHASES
        for qid in cohorts[phase]
    }
    indexed = {}
    grouped = defaultdict(list)
    for row in decisions:
        key = (row["stage"], row["phase"], row["question_id"], row["arm"])
        if key not in expected_choices or key in indexed:
            raise ValueError("unexpected, duplicated or missing original shadow row")
        cal = by_fit[row["stage"], row["arm"], row["cell"]]
        successful = row["status"] == "succeeded"
        require(
            row["cell"] == routes[row["question_id"]]
            and row["role"] == "shadow-source-only-no-Reader-execution"
            and row["chosen_scale"] == cal["receipt"]["chosen_scale"]
            and row["head_sha256"] == cal["checkpoint_head_sha256"]
            and row["actual_reader_executions"] == 0
            and row["native_targets_unread"] is True
            and row["status"] in ("succeeded", "failed"),
            "shadow decision selected using wrong Head, Cell, labels or Reader",
        )
        if successful:
            require(
                type(row["selected_index"]) is int
                and type(row["frozen_index"]) is int
                and isinstance(row["original_pool_digest"], str)
                and len(row["original_pool_digest"]) == 64
                and isinstance(row["selected_source_id"], str)
                and bool(row["selected_source_id"]),
                "unbound frozen-vs-shadow observed selection",
            )
        indexed[key] = row
        grouped[(row["stage"], row["arm"], row["cell"], row["phase"])].append(row)
    require(
        len(decisions) == len(indexed) == len(expected_choices) == 480
        and set(indexed) == expected_choices,
        "original 480 shadow source-only question choices incomplete",
    )
    require(
        provenance["source_choices_verified"] == 480
        and provenance["planned_shadow_source_choices"] == 480
        and provenance["planned_shadow_calibrations"] == 30
        and provenance["no_gold_target_read"] is True
        and provenance["no_additional_reader_call"] is True
        and provenance["production_accepted"] is False,
        "source-only shadow provenance mutated",
    )
    results = postpolicy["results"]
    require(
        postpolicy["planned_shadow_choices"] == 480
        and postpolicy["labels_opened_only_after_all_model_decisions"] is True
        and postpolicy["production_accepted"] is False
        and set(results) == {"/".join(map(str, k)) for k in grouped},
        "post-policy weak document labels or complete phase census missing",
    )
    for key, rows in grouped.items():
        receipt = results["/".join(map(str, key))]
        n = len(rows)
        observed = [x for x in rows if x["status"] == "succeeded"]
        changes = sum(x["selected_index"] != x["frozen_index"] for x in observed)
        require(
            receipt["planned"] == n
            and receipt["successful_choices"] == len(observed)
            and receipt["failed_choices"] == n - len(observed)
            and receipt["changed_source_top1"] == changes
            and receipt["source_scored"] <= n
            and receipt["shadow_weak_source_gains"] >= 0
            and receipt["shadow_weak_source_regressions"] >= 0
            and receipt["shadow_weak_source_gains"]
            + receipt["shadow_weak_source_regressions"]
            <= changes
            and receipt["semantic_entailment_judged"] is False
            and receipt["reader_called_for_shadow"] is False,
            "post-policy weak source score not aligned to sealed shadow choices",
        )
    decisions_by_stage_arm = {}
    for stage in STAGES:
        for arm in ARMS:
            per_phase = {}
            for phase in ("test", "transfer"):
                receipts = [results[f"{stage}/{arm}/{cell}/{phase}"] for cell in CELLS]
                totals = Counter()
                for rec in receipts:
                    for field in (
                        "planned",
                        "source_scored",
                        "changed_source_top1",
                        "shadow_weak_source_gains",
                        "shadow_weak_source_regressions",
                    ):
                        totals[field] += rec[field]
                require(
                    totals["planned"] == 8
                    and totals["source_scored"] <= totals["planned"],
                    "held-out shadow question subject count changed",
                )
                per_phase[phase] = dict(totals)
            test, transfer = per_phase["test"], per_phase["transfer"]
            # A source-only shadow candidate requires strictly positive net
            # support improvement in BOTH phases. This is a rejection gate,
            # not evidence of independent semantic or production superiority.
            positive_in_both = (
                test["shadow_weak_source_gains"]
                > test["shadow_weak_source_regressions"]
                and transfer["shadow_weak_source_gains"]
                > transfer["shadow_weak_source_regressions"]
            )
            decisions_by_stage_arm[f"{stage}/{arm}"] = dict(
                selected_train_scale_by_cell={
                    cell: by_fit[stage, arm, cell]["receipt"]["chosen_scale"]
                    for cell in CELLS
                },
                heldout_test=per_phase["test"],
                heldout_transfer=per_phase["transfer"],
                source_only_rejection=not positive_in_both,
                eligible_for_new_reader_experiment_from_this_negative_gate=positive_in_both,
                actual_reader_executions=0,
                independent_family_semantic_verdict=None,
                production_accepted=False,
            )
    return dict(
        schema="hepta.stem-shadow-retrospective-negative-gate.v1",
        archive_source_commit=SOURCE,
        actual_choice_census=len(decisions),
        actual_training_calibrations=len(calibrations),
        repeatedly_observed_heldout_questions_not_independent_trials=True,
        test_and_transfer_labels_not_used_for_scale_selection=True,
        source_document_support_not_semantic_entailment=True,
        no_new_reader_calls=True,
        by_stage_arm=decisions_by_stage_arm,
        final_checkpoint_rejected_arms=[
            arm
            for arm in ARMS
            if decisions_by_stage_arm[f"48/{arm}"]["source_only_rejection"]
        ],
        none_of_five_arms_qualified_for_shadow_reader_at_48=all(
            decisions_by_stage_arm[f"48/{arm}"]["source_only_rejection"] for arm in ARMS
        ),
        semantic_citation_precision=None,
        production_accepted=False,
    )


def audit_zip(archive_path):
    archive = PinnedArchive(Path(archive_path), ZIP_SHA)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == SOURCE
            and archive.read("tested-tree.txt").decode().strip() == TREE,
            "strict-source shadow artifact commit/tree mismatch",
        )
        report = audit_shadow(
            archive.json("comparison/preregistered.json"),
            archive.jsonl("comparison/shadow-train-calibration.jsonl"),
            archive.jsonl("comparison/shadow-source-decisions.jsonl"),
            archive.json("comparison/shadow-provenance.json"),
            archive.json("comparison/shadow-source-ceiling.json"),
        )
        report["immutable_zip_sha256"] = archive.sha256
        report["verified_archive_members"] = archive.manifest_entries
        return report
    finally:
        archive.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit_zip(args.archive)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
