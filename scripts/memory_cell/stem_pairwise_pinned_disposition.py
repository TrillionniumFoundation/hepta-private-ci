"""Read-only, hash-pinned evidence for the completed 192-decision pairwise shadow.

An experimental positive-vs-weak-negative source ranking is NOT a validated
Reader answer, held-out-family effect, or entailed citation. No model is loaded;
all original 576 policy decisions are preserved byte for byte in the ZIP.
"""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from stem_audit_archive import PinnedArchive, require
from stem_native_nonpromotion import audit_nonpromotion

SOURCE = "6235ccfb3ffc495c45284ff13f1e98b1644e31c2"
TREE = "fcb329b7416b75d49624e500d4079f076fc86286"
ZIP_SHA256 = "694401ca61859bd11a24ae212c0edb4c3b493182581e07d373cc73f4fd0aeae1"
ARTIFACT_ID = 11756269634
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
ARMS = ("frozen_rerank", "prototype", "linear", "gated",
        "lineage_lora_gated", "independent_lora_gated")
SHADOWS = ("pairwise_linear", "pairwise_gated")
CELLS = ("general", "temporal")


def audit_native_pairwise_receipts(plan, original, fits, choices, posthoc,
                                   report, model_payloads):
    """Match every archived counterfactual Head to original frozen question.

    The POSTPOLICY document-support gains are reported as claims from the
    archived reviewer, not independently recomputed semantic correctness.
    """
    cohorts = plan["questions"]
    all_ids = [q for group in cohorts.values() for q in group]
    require(
        plan["source_commit"] == SOURCE
        and tuple(plan["curriculum_attempted_examples"]) == STAGES
        and tuple(plan["arms"]) == ARMS
        and tuple(plan["cells"]) == CELLS
        and set(cohorts) == {"train", *PHASES}
        and len(cohorts["train"]) == 48
        and all(len(cohorts[p]) == 8 for p in PHASES)
        and len(all_ids) == len(set(all_ids)) == 80
        and set(plan["routes"]) == set(all_ids)
        and all(c in CELLS for c in plan["routes"].values())
        and plan["source_visibility_policy"]
        == "strict-as-of-before-index-and-every-Encoder-v1",
        "source, cohort, Cell or temporal admission registration drift",
    )
    expected_policy = {
        (stage, phase, q, arm)
        for stage in STAGES for phase in PHASES
        for q in cohorts[phase] for arm in ARMS
    }
    policy, original_reader_failures = {}, 0
    for row in original:
        key = (row["stage"], row["phase"], row["question_id"], row["arm"])
        require(key in expected_policy and key not in policy,
                "unregistered or duplicated original policy")
        require(row["status"] in ("succeeded", "failed"),
                "unknown original policy status")
        policy[key] = row
        original_reader_failures += row["status"] == "failed"
    require(len(policy) == len(original) == len(expected_policy) == 576,
            "entire unmodified original six-arm denominator required")

    expected_fit = {
        (stage, arm, cell)
        for stage in STAGES for arm in SHADOWS for cell in CELLS
    }
    by_fit, fit_failures, previous = {}, 0, {}
    for item in fits:
        key = item["stage"], item["arm"], item["cell"]
        require(key in expected_fit and key not in by_fit
                and item["status"] in ("succeeded", "failed")
                and item["role"] == "nonqualifying-native-pairwise-no-reader-shadow",
                "missing or duplicated nonqualifying pairwise Head fit")
        if item["status"] == "succeeded":
            receipt = item["receipt"]
            name = item["model_file_name"]
            payload = model_payloads.get(name)
            require(
                isinstance(payload, bytes)
                and item["model_bytes"] == len(payload)
                and sha256(payload).hexdigest() == item["final_head_sha256"]
                and item["final_head_sha256"] == receipt["checkpoint_post_sha256"]
                and item["initial_head_sha256"] == receipt["checkpoint_pre_sha256"]
                and receipt["strictly_train_source_only"] is True
                and receipt["null_weights_unchanged"] is True
                and receipt["original_six_arms_unchanged"] is True
                and receipt["observed_original_reader_calls"] == 0
                and receipt["weak_distractors_not_verified_hard_negatives"] is True
                and receipt["actual_heldout_task_gain_established"] is False
                and receipt["heldout_annotations_seen"] is False
                and receipt["production_accepted"] is False
                and item["artifact_reload_matched"] is True,
                "saved pairwise Head, null weights, TRAIN isolation or receipt drift",
            )
            chain = previous.get((item["arm"], item["cell"]))
            if chain is not None:
                require(chain == item["initial_head_sha256"],
                        "resumed pairwise Head does not follow prior checkpoint")
            previous[(item["arm"], item["cell"])] = item["final_head_sha256"]
        else:
            fit_failures += 1
        by_fit[key] = item
    require(set(by_fit) == expected_fit and len(fits) == 12,
            "missing original 12 actual pairwise Head fits")

    expected_choices = {
        (stage, phase, q, arm)
        for stage in STAGES for phase in PHASES
        for q in cohorts[phase] for arm in SHADOWS
    }
    choice, grouped = {}, {}
    for row in choices:
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        require(key in expected_choices and key not in choice,
                "duplicate, missing or unregistered label-blind shadow")
        base = policy[(row["stage"], row["phase"], row["question_id"],
                       "frozen_rerank")]
        fit = by_fit[(row["stage"], row["arm"], row["cell"])]
        require(
            row["status"] in ("succeeded", "failed")
            and row["cell"] == base["cell"] == plan["routes"][row["question_id"]]
            and row["family"] == base["family"]
            and row["training_labels_or_test_gold_in_answer"] is False
            and row["actual_reader_calls"] == 0
            and row["pool_digest"] == base.get("pool_digest")
            and row["frozen_feature_digest"] == base.get("feature_digest"),
            "shadow choice changed source Cell, features, Reader or label exposure",
        )
        if row["status"] == "succeeded":
            require(
                fit["status"] == "succeeded"
                and row["head_sha256"] == fit["final_head_sha256"]
                and row["original_frozen_selected"] == base.get("selected")
                and type(row["selected"]) is int
                and 0 <= row["selected"] < row["candidate_count"]
                and row["candidate_count"] >= 2
                and isinstance(row["candidate_ids_digest"], str)
                and len(row["candidate_ids_digest"]) == 64,
                "label-blind Head choice differs from frozen feature or fitted artifact",
            )
        choice[key] = row
        grouped.setdefault((row["stage"], row["phase"], row["arm"]), []).append(row)
    require(len(choice) == len(choices) == len(expected_choices) == 192,
            "incomplete exactly-192 source-only shadow denominator")
    # The immutable generating artifact predates the v2 enriched counters.
    # Verify its *actual* v1 contract instead of manufacturing absent v2
    # fields or changing the original report to claim a new execution.
    version = posthoc.get("schema")
    legacy = version == "hepta.stem-pairwise-native-source-only-shadow.v1"
    modern = version == "hepta.stem-pairwise-native-source-only-shadow.v2"
    require(legacy or modern, "unknown original source-only shadow schema")
    require(
        posthoc["total_label_blind_decisions"] == 192
        and posthoc["observed_reader_calls"] == 0
        and posthoc["original_six_arm_policy_attempts_unmodified"] is True
        and posthoc["production_accepted"] is False
        and posthoc["independently_established_generalization"] is False,
        "post-policy source-only result falsely promoted",
    )
    if legacy:
        # v1 recorded the fits and weak-label status but never a verified
        # no-gold flag or citation verdict. Every original decision was checked
        # above for zero Reader calls and no benchmark labels; those properties
        # must not be reissued as a v2 reviewer certification.
        require(
            set(posthoc) == {
                "schema", "fits", "original_six_arm_policy_attempts_unmodified",
                "total_label_blind_decisions", "observed_reader_calls",
                "weak_negative_documents_not_independent_entailment",
                "by_checkpoint_phase_arm", "production_accepted",
                "independently_established_generalization",
            }
            and posthoc["fits"] == fits
            and posthoc["weak_negative_documents_not_independent_entailment"] is True,
            "legacy postpolicy fields or original fit census drift",
        )
    else:
        require(
            posthoc["no_reader_calls_or_evaluation_labels_in_shadow_decision_verified"]
            is True and posthoc["semantic_citation_precision"] is None,
            "modern postpolicy source-only certification drift",
        )
    by_source = posthoc["by_checkpoint_phase_arm"]
    results, total = {}, Counter()
    for stage in STAGES:
        for phase in PHASES:
            for arm in SHADOWS:
                group = grouped[(stage, phase, arm)]
                key = f"{stage}/{phase}/{arm}"
                row = by_source[key]
                frozen_absent = shadow_failed = seen = flips = reader_failed = 0
                for shadow in group:
                    base = policy[(stage, phase, shadow["question_id"],
                                   "frozen_rerank")]
                    if base.get("selected") is None:
                        frozen_absent += 1
                        continue
                    if shadow["status"] != "succeeded":
                        shadow_failed += 1
                        continue
                    seen += 1
                    flips += shadow["selected"] != base["selected"]
                    reader_failed += base["status"] != "succeeded"
                scored = row["source_label_scored"]
                uncertain = row["source_label_unresolved_or_failure"]
                gains = row["native_weak_support_gains"]
                regressions = row["native_weak_support_regressions"]
                require(
                    len(group) == row["attempted"] == 8
                    and row["selection_changed"] == flips
                    and type(scored) is int and type(uncertain) is int
                    and type(gains) is int and type(regressions) is int
                    and 0 <= scored <= 8 and 0 <= uncertain <= 8
                    and scored + uncertain == 8
                    and 0 <= gains <= scored
                    and 0 <= regressions <= scored
                    and gains + regressions <= flips,
                    "post-hoc weak source gains differ from original sealed choices",
                )
                if legacy:
                    require(
                        set(row) == {
                            "attempted", "selection_changed", "source_label_scored",
                            "source_label_unresolved_or_failure",
                            "native_weak_support_gains",
                            "native_weak_support_regressions",
                            "original_reader_answer_reused_as_shadow",
                            "semantic_citation_precision",
                        }
                        and row["original_reader_answer_reused_as_shadow"] is False
                        and row["semantic_citation_precision"] is None,
                        "legacy weak-label result claimed reused Reader or citation verdict",
                    )
                else:
                    require(
                        row["source_selection_pairs_observed"] == seen
                        and row["baseline_reader_failed_with_top1"] == reader_failed
                        and row["frozen_selector_unobserved_or_empty"] == frozen_absent
                        and row["shadow_selection_failed_with_baseline_top1"]
                        == shadow_failed,
                        "modern source selection counters differ from original decisions",
                    )
                results[key] = dict(
                    original_questions=8, observed_source_pairs=seen,
                    frozen_reader_failures_retained=reader_failed,
                    pairwise_source_rank_changes=flips,
                    weak_document_label_scored=scored,
                    weak_document_source_gains=gains,
                    weak_document_source_regressions=regressions,
                    unresolved_or_failed_original_evidence=uncertain,
                )
                for k, v in (
                    ("pairs", seen), ("rank_changes", flips),
                    ("weak_label_gains", gains), ("weak_label_regressions", regressions),
                    ("scored", scored), ("uncertain", uncertain),
                ):
                    total[k] += v
    require(set(results) == set(by_source) and len(results) == 24,
            "missing or extra post-hoc shadow phase results")
    # Reject a forged acceptance bit with this audit's own fail-closed
    # contract BEFORE invoking the generic nonpromotion audit. The generic
    # utility can raise ValueError for invalid data; the source-pinned
    # artifact validator must retain an explicit AuditError boundary.
    require(
        isinstance(report, dict)
        and report.get("logical_policy_attempts") == 576
        and report.get("production_accepted") is False,
        "unqualified native run promoted itself",
    )
    nonpromotion = audit_nonpromotion(report)
    require(
        report["logical_policy_attempts"] == 576
        and report["production_accepted"] is False
        and report["native_pairwise_shadow_source_only"] == posthoc
        and report["reader"]["actual_failed_attempts"] == 0
        and original_reader_failures == 0
        and nonpromotion["scale_out_permitted"] is False,
        "original frozen Reader policy or nonpromotion verdict changed",
    )
    return dict(
        schema="hepta.stem-native-pairwise-pinned-disposition.v1",
        source_commit=SOURCE, registered_stages=list(STAGES),
        shadow_training_fit_attempts=12,
        shadow_training_fit_failures=fit_failures,
        original_policy_attempts=576,
        original_policy_execution_failures=original_reader_failures,
        shadow_source_decisions=len(choices),
        original_shadow_schema=version,
        legacy_v1_missing_enriched_counters=legacy,
        original_v1_not_relabelled_as_v2=True,
        shadow_reader_model_calls=0,
        observed_weak_document_source_counts=dict(total),
        by_stage_phase_arm=results,
        original_arms_no_independent_task_superiority=not nonpromotion[
            "any_aggregate_source_or_answer_gain"
        ],
        weak_native_document_support_not_entailment=True,
        shadow_reader_answer_quality_measured=False,
        posthoc_label_selection_not_hyperparameter_search=True,
        independent_semantic_citation_precision=None,
        prospective_independent_family_benefit_qualified=False,
        production_accepted=False, scale_out_permitted=False,
    )


def audit_pinned_archive(path):
    artifact = PinnedArchive(path, ZIP_SHA256)
    try:
        require(artifact.read("tested-commit.txt").decode().strip() == SOURCE,
                "native model-execution commit is not pinned")
        require(artifact.read("tested-tree.txt").decode().strip() == TREE,
                "native model-execution source-tree mismatch")
        fits = artifact.json("comparison/pairwise-shadow-train-fits.json")
        saved = {
            item["model_file_name"]:
            artifact.read("comparison/" + item["model_file_name"])
            for item in fits if item["status"] == "succeeded"
        }
        result = audit_native_pairwise_receipts(
            artifact.json("comparison/preregistered.json"),
            artifact.jsonl("comparison/policy-predictions.jsonl"),
            fits,
            artifact.jsonl("comparison/pairwise-shadow-label-blind-choices.jsonl"),
            artifact.json("comparison/pairwise-shadow-posthoc-source-support.json"),
            artifact.json("comparison/report.json"),
            saved,
        )
        result["transport_zip_sha256"] = artifact.sha256
        result["verified_sha256_manifest_entries"] = artifact.manifest_entries
        result["source_tree_sha256"] = TREE
        result["artifact_id"] = ARTIFACT_ID
        return result
    finally:
        artifact.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = audit_pinned_archive(args.archive)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
