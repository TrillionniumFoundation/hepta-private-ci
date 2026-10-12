"""Independently reject promotion of the October 12 strict native 576-run.

Only reads an externally SHA-256-pinned completed GitHub artifact and its
internal SHA256SUMS. Reuses independent native pairing, loss and effective-N
audits. Never loads a model, trains, retunes, or authenticates reviewers.
"""

import argparse
import json
from pathlib import Path

from stem_audit_archive import PinnedArchive, require
from stem_effective_n import effective_heldout_subjects
from stem_native_nonpromotion import (
    audit_nonpromotion,
    audit_exact_paired_choices,
)

SOURCE = "d0f69d7b94f65730fa1e093dee6989916f01898e"
TREE = "87e3b17a0601c17712b9512fc01eadc123060391"
ZIP_SHA256 = "07b0f15ec150cc9817db6bfc9b4bae1e2c06a5296ca2ba3c4c7895da18b99e2f"
ORIGINAL_RUN = 38202116864
ARTIFACT_ID = 11726530850
ARMS = ("prototype", "linear", "gated", "lineage_lora_gated",
        "independent_lora_gated")


def interpret_current(gate, exact, panel):
    """Return a fail-closed no-promotion verdict, not an adoption certificate."""
    require(
        gate["schema"] == "hepta.stem-native-nonpromotion-gate.v1"
        and gate["audited_policy_attempts"] == 576
        and gate["policy_execution_failures"] == 0
        and gate["citation_markers"] == 0
        and gate["production_accepted"] is False
        and gate["scale_out_permitted"] is False
        and exact["schema"] == "hepta.stem-strict-exact-paired-nonpromotion.v1"
        and exact["full_policy_attempts"] == 576
        and exact["exact_original_scored_receipt_matches"] == 576
        and exact["full_policy_execution_failures"] == 0
        and exact["raw_emitted_citation_markers"] == 0
        and exact["heldout_test_transfer_unique_questions"] == 16
        and exact["head_training_checkpoints"] == 30
        and exact["production_accepted"] is False
        and exact["scale_out_permitted"] is False
        and panel["schema"] == "hepta.stem-effective-heldout-repeated-panel.v3"
        and panel["independent_question_ids_per_arm"] == 16
        and panel["repeated_question_evaluations_per_arm"] == 48
        and panel["source_family_sampling_independence_certified"] is False
        and panel["production_accepted"] is False
        and set(exact["learned_arms"]) == set(ARMS)
        and set(gate["learning_arms"]) == set(ARMS),
        "incomplete, contradictory or promoted strict-run receipt",
    )
    changes = {
        arm: dict(
            matched=exact["learned_arms"][arm]["matched_policy_pairs"],
            changed_top1=exact["learned_arms"][arm]["changed_source_top1"],
            changed_answer_bytes=exact["learned_arms"][arm][
                "changed_original_answer_bytes"
            ],
            native_support_gains=exact["learned_arms"][arm][
                "weak_native_support_gains"
            ],
            native_support_regressions=exact["learned_arms"][arm][
                "weak_native_support_regressions"
            ],
        )
        for arm in ARMS
    }
    require(
        all(
            row["matched"] == 96
            and row["changed_top1"] == (
                1 if arm == "lineage_lora_gated" else 0
            )
            and row["changed_answer_bytes"] == 0
            and row["native_support_gains"] == row["native_support_regressions"] == 0
            for arm, row in changes.items()
        ),
        "completed native source differs from pinned no-learning observation",
    )
    return dict(
        schema="hepta.stem-strict-20261012-rejection.v1",
        original_run_id=ORIGINAL_RUN,
        immutable_artifact_id=ARTIFACT_ID,
        source_commit=SOURCE,
        source_tree=TREE,
        complete_original_policy_attempts=576,
        failed_policy_attempts=0,
        independent_test_transfer_question_units_per_arm=16,
        repeated_checkpoint_observations_per_arm=48,
        emitted_citation_markers=0,
        learned_arms=changes,
        exactly_one_real_selection_flip_with_no_support_gain=True,
        heldout_test_transfer_selection_flips=0,
        no_observed_learner_vs_frozen_correct_decision_gain=True,
        success_is_operational_not_generalization=True,
        no_independent_citation_entailment_review=True,
        prospective_source_family_effect_proven=False,
        p95_energy_and_dollar_tco_verified=False,
        semantic_citation_precision=None,
        scale_out_permitted=False,
        production_accepted=False,
    )


def confirm_sole_real_selection_flip(plan, original, scored):
    """Pin the ONLY genuine strict-run Head selection change to its source."""
    if len(original) != 576 or len(scored) != 576:
        raise ValueError("576 original and scored rows required")
    observed = {
        (r["stage"], r["phase"], r["question_id"], r["arm"]): r
        for r in original
    }
    evaluated = {
        (r["stage"], r["phase"], r["question_id"], r["arm"]): r
        for r in scored
    }
    require(
        len(observed) == len(evaluated) == 576
        and set(observed) == set(evaluated),
        "duplicate or unpaired original rank decisions",
    )
    flips = []
    for (stage, phase, question_id, arm), learned in observed.items():
        if arm == "frozen_rerank":
            continue
        frozen = observed[(stage, phase, question_id, "frozen_rerank")]
        if learned["selected"] == frozen["selected"]:
            continue
        a = evaluated[(stage, phase, question_id, "frozen_rerank")]
        b = evaluated[(stage, phase, question_id, arm)]
        require(
            frozen["pool_digest"] == learned["pool_digest"]
            and frozen["family"] == learned["family"]
            and frozen["cell"] == learned["cell"]
            and frozen["receipt"]["generator_identity"]
            == learned["receipt"]["generator_identity"]
            and frozen["receipt"]["generator_profile"]
            == learned["receipt"]["generator_profile"]
            and frozen["answer"] == learned["answer"],
            "unequal Reader/pool or changed answer behind rank difference",
        )
        flips.append(dict(
            stage=stage, phase=phase, question_id=question_id, arm=arm,
            frozen_selected=frozen["selected"],
            learned_selected=learned["selected"],
            frozen_weak_native_support=a["source_choice_correct"],
            learned_weak_native_support=b["source_choice_correct"],
            answer_bytes_changed=frozen["answer"] != learned["answer"],
        ))
    expected = [dict(
        stage=48, phase="retention", question_id="locomo:conv-43/q217",
        arm="lineage_lora_gated", frozen_selected=1, learned_selected=7,
        frozen_weak_native_support=0, learned_weak_native_support=0,
        answer_bytes_changed=False,
    )]
    require(
        flips == expected,
        "previously unreviewed or displaced native candidate choice",
    )
    return flips


def audit_zip(path):
    archive = PinnedArchive(path, ZIP_SHA256)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == SOURCE
            and archive.read("tested-tree.txt").decode().strip() == TREE,
            "immutable generating commit/tree mismatch",
        )
        plan = archive.json("comparison/preregistered.json")
        require(
            plan["source_commit"] == SOURCE
            and plan["source_visibility_policy"]
            == "strict-as-of-before-index-and-every-Encoder-v1",
            "original source or as-of evidence admission changed",
        )
        report = archive.json("comparison/report.json")
        raw = archive.jsonl("comparison/policy-predictions.jsonl")
        scored = archive.json("comparison/scored-policy-attempts.json")
        fit = archive.json("comparison/within-head-train-fit.json")
        ceiling = archive.json("comparison/post-policy-native-source-ceiling.json")
        panel = effective_heldout_subjects(
            plan, report["train_to_heldout_diagnostic"]
        )
        gate = audit_nonpromotion(report)
        exact = audit_exact_paired_choices(
            plan, raw, scored, report, fit, ceiling, panel
        )
        verdict = interpret_current(gate, exact, panel)
        verdict["verified_real_selection_flips"] = confirm_sole_real_selection_flip(
            plan, raw, scored
        )
        verdict.update(
            verified_external_zip_sha256=archive.sha256,
            verified_internal_file_digests=archive.manifest_entries,
            archive_members_stored_without_extraction=True,
            independent_audits=dict(aggregate=gate, exact_paired=exact),
        )
        return verdict
    finally:
        archive.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit_zip(args.archive)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2, sort_keys=True, allow_nan=False)
        file.write("\n")
    print(json.dumps(dict(
        schema=result["schema"],
        run=result["original_run_id"],
        original_policy_attempts=result["complete_original_policy_attempts"],
        learned_arms=result["learned_arms"],
        production_accepted=False,
    ), sort_keys=True))


if __name__ == "__main__":
    main()
