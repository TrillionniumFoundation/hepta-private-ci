"""Independent, immutable Oct-13 strict Stem shadow/readout experiment audit.

Read only ONE externally SHA-256 pinned, successful native artifact ZIP and
reconcile original frozen/learned top-1, budget-matched CE-vs-pairwise shadows,
weak-label placebo and actual post-policy shadow Reader calls. The earlier
six-arm matrix, original pre/post source observations and Reader receipts
remain untouched. No model/optimizer, semantic judging or new inference.
"""

import argparse
import json
from pathlib import Path

from stem_audit_archive import PinnedArchive, require

SOURCE = "1081d37f8ef8b75a4e6718d8dfccb4e5dfe19bda"
TREE = "2e78823aa92d593c9dfb84a540712743efef7e48"
ZIP_SHA256 = "c32408fa3d1f8fdea66c208069e18b10ab44c4232d92604c7a5f4beb84c4902a"
ARTIFACT_ID = 11832820287
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
SHADOWS = ("pairwise_linear", "pairwise_gated")
KINDS = ("linear", "gated")
OBJECTIVES = ("multi_positive_ce", "positive_vs_weak_negative")


def _nonnegative(value, label):
    require(type(value) is int and value >= 0, "invalid count: " + label)
    return value


def _complete_index(rows, expected, columns, label):
    result = {}
    for row in rows:
        key = tuple(row[x] for x in columns)
        require(
            key in expected and key not in result, "duplicate or unregistered " + label
        )
        result[key] = row
    require(
        set(result) == expected and len(result) == len(expected),
        "incomplete original " + label + " census",
    )
    return result


def audit_reports(
    plan,
    policies,
    pairwise_choices,
    objective_choices,
    placebo_choices,
    pair_report,
    objective_report,
    placebo_report,
    reader_report,
    matrix_report,
):
    require(
        plan["source_commit"] == SOURCE
        and plan["source_visibility_policy"]
        == "strict-as-of-before-index-and-every-Encoder-v1"
        and tuple(plan["arms"]) == ARMS
        and tuple(plan["curriculum_attempted_examples"]) == STAGES,
        "changed source, policy or model registration",
    )
    cohorts = plan["questions"]
    require(
        set(cohorts) == {"train", *PHASES}
        and len(cohorts["train"]) == 48
        and all(len(cohorts[x]) == 8 for x in PHASES)
        and len({q for group in cohorts.values() for q in group}) == 80,
        "historical 80-question cohort drift",
    )
    expected = {
        (stage, phase, q, arm)
        for stage in STAGES
        for phase in PHASES
        for q in cohorts[phase]
        for arm in ARMS
    }
    original = _complete_index(
        policies,
        expected,
        ("stage", "phase", "question_id", "arm"),
        "original policy",
    )
    require(
        len(original) == 576
        and all(row["status"] == "succeeded" for row in original.values())
        and matrix_report["census"]
        == {"planned": 576, "recorded": 576, "complete": True}
        and matrix_report["production_accepted"] is False
        and matrix_report["semantic_citation_precision"] is None,
        "original strict successful matrix has changed",
    )
    baseline = {}
    for stage in STAGES:
        for phase in PHASES:
            for q in cohorts[phase]:
                frozen = original[stage, phase, q, ARMS[0]]
                require(
                    type(frozen.get("selected")) is int
                    and 0 <= frozen["selected"] < 64
                    and frozen.get("pool_digest")
                    and frozen["receipt"]["generator_parameter_updates"] == 0,
                    "frozen Reader selection or weight snapshot absent",
                )
                baseline[stage, phase, q] = frozen
    original_arms = {}
    for arm in ARMS[1:]:
        changed = 0
        for stage in STAGES:
            for phase in PHASES:
                for q in cohorts[phase]:
                    b = baseline[stage, phase, q]
                    x = original[stage, phase, q, arm]
                    require(
                        x["pool_digest"] == b["pool_digest"]
                        and x["family"] == b["family"],
                        "original six arm candidate/source-family drift",
                    )
                    changed += x["selected"] != b["selected"]
        original_arms[arm] = dict(
            paired_original_attempts=96,
            changed_frozen_top1=changed,
            no_independent_learning_benefit_certified=True,
        )

    paired_expected = {
        (stage, phase, q, arm)
        for stage in STAGES
        for phase in PHASES
        for q in cohorts[phase]
        for arm in SHADOWS
    }
    by_pair = _complete_index(
        pairwise_choices,
        paired_expected,
        ("stage", "phase", "question_id", "arm"),
        "192 label-blind pairwise choices",
    )
    require(
        all(
            row["status"] in ("succeeded", "failed")
            and row["actual_reader_calls"] == 0
            and row["training_labels_or_test_gold_in_answer"] is False
            for row in by_pair.values()
        ),
        "source-only shadow obtained answers or held-out labels",
    )
    objective_expected = {
        (stage, phase, q, kind, objective)
        for stage in STAGES
        for phase in PHASES
        for q in cohorts[phase]
        for kind in KINDS
        for objective in OBJECTIVES
    }
    by_obj = _complete_index(
        objective_choices,
        objective_expected,
        ("stage", "phase", "question_id", "kind", "objective"),
        "384 matched-objective choices",
    )
    require(
        all(row["status"] in ("succeeded", "failed") for row in by_obj.values()),
        "unrecognized shadow objective execution status",
    )
    require(
        len(placebo_choices) == 384
        and placebo_report["sealed_choices"] == 384
        and placebo_report["trained_heads"] == 24
        and placebo_report["production_accepted"] is False,
        "unavailable label-placebo control census",
    )

    require(
        pair_report["total_label_blind_decisions"] == 192
        and pair_report["observed_reader_calls"] == 0
        and pair_report["production_accepted"] is False
        and pair_report["independently_established_generalization"] is False,
        "pairwise source-only controls changed",
    )
    require(
        objective_report["label_blind_shadow_decisions"] == 384
        and objective_report["fitted_objective_checkpoints"] == 24
        and objective_report["training_questions_same_for_both_objectives"] is True
        and objective_report["initial_head_weights_identical"] is True
        and objective_report["no_original_policy_or_reader_mutation"] is True
        and objective_report["production_accepted"] is False,
        "budget-matched CE/pairwise provenance changed",
    )
    require(
        reader_report["planned_reader_controls"] == 32
        and reader_report["same_fixed_reader_weights_prompt_generation"] is True
        and reader_report["original_576_policy_answers_unchanged"] is True
        and reader_report["production_accepted"] is False
        and reader_report["independent_prospective_generalization"] is False,
        "32 additional post-policy Reader controls changed",
    )
    pair_summaries = pair_report["by_checkpoint_phase_arm"]
    objective_summaries = objective_report["by_stage_phase_kind"]
    placebo_summaries = placebo_report["by_stage_phase_kind"]
    reader_summaries = reader_report["per_phase_arm"]
    require(
        set(pair_summaries)
        == {f"{s}/{p}/{a}" for s in STAGES for p in PHASES for a in SHADOWS}
        and set(objective_summaries)
        == {f"{s}/{p}/{a}" for s in STAGES for p in PHASES for a in KINDS}
        and set(placebo_summaries) == set(objective_summaries)
        and set(reader_summaries)
        == {f"{p}/{a}" for p in ("test", "transfer") for a in SHADOWS},
        "one or more shadow/review denominators missing",
    )

    def validate_pair(data):
        n = _nonnegative(data["attempted"], "pairwise attempted")
        scored = _nonnegative(data["source_label_scored"], "pairwise scored")
        missing = _nonnegative(
            data["source_label_unresolved_or_failure"], "pairwise missing"
        )
        changed = _nonnegative(data["selection_changed"], "pairwise flips")
        gains = _nonnegative(data["native_weak_support_gains"], "pairwise gains")
        regress = _nonnegative(
            data["native_weak_support_regressions"], "pairwise losses"
        )
        require(
            n == scored + missing == 8 and changed <= 8 and gains + regress <= scored,
            "invalid original pairwise opportunity/failure denominator",
        )

    def validate_objective(data):
        n = _nonnegative(data["attempted"], "objective attempted")
        scored = _nonnegative(data["native_weak_source_scored"], "objective scored")
        missing = _nonnegative(data["unscored_or_failed"], "objective missing")
        wins = _nonnegative(
            data["pairwise_over_ce_weak_source_gains"], "pairwise relative wins"
        )
        loses = _nonnegative(
            data["ce_over_pairwise_weak_source_gains"], "CE relative wins"
        )
        require(
            n == scored + missing == 8 and wins + loses <= scored,
            "invalid 8-question objective-vs-CE comparison denominator",
        )

    def validate_placebo(data):
        n = _nonnegative(data["attempted"], "placebo attempted")
        scored = _nonnegative(data["weak_source_scored"], "placebo scored")
        missing = _nonnegative(data["failed_or_unresolved"], "placebo missing")
        wins = _nonnegative(
            data["real_label_over_placebo_weak_source_wins"], "placebo wins"
        )
        losses = _nonnegative(
            data["placebo_over_real_label_weak_source_wins"], "placebo losses"
        )
        require(
            n == scored + missing == 8 and wins + losses <= scored,
            "invalid label-control placebo denominator",
        )

    def validate_reader(data):
        n = _nonnegative(data["attempted"], "shadow Reader attempted")
        scored = _nonnegative(data["scored_matched_answers"], "reader scored")
        missing = _nonnegative(data["missing_failed_or_unscorable"], "reader unscored")
        changed = _nonnegative(data["source_changed"], "reader source flips")
        require(
            n == scored + missing == 8
            and changed <= 8
            and data["semantic_citation_precision"] is None
            and data["independent_source_entailment_judged"] is False,
            "invalid real Reader comparison or semantic-citation claim",
        )

    for row in pair_summaries.values():
        validate_pair(row)
    for row in objective_summaries.values():
        validate_objective(row)
    for row in placebo_summaries.values():
        validate_placebo(row)
    for row in reader_summaries.values():
        validate_reader(row)

    final = {}
    for phase in ("test", "transfer"):
        final[phase] = {}
        for kind in KINDS:
            shadow = pair_summaries[f"48/{phase}/pairwise_{kind}"]
            matched = objective_summaries[f"48/{phase}/{kind}"]
            placebo = placebo_summaries[f"48/{phase}/{kind}"]
            reader = reader_summaries[f"{phase}/pairwise_{kind}"]
            final[phase][kind] = dict(
                original_distinct_questions=8,
                pairwise_source_selection_changes=shadow["selection_changed"],
                pairwise_weak_native_support_gains=shadow["native_weak_support_gains"],
                pairwise_weak_native_support_regressions=shadow[
                    "native_weak_support_regressions"
                ],
                matched_objective_pairwise_over_CE_support_wins=matched[
                    "pairwise_over_ce_weak_source_gains"
                ],
                matched_objective_CE_over_pairwise_support_wins=matched[
                    "ce_over_pairwise_weak_source_gains"
                ],
                real_training_labels_over_placebo_support_wins=placebo[
                    "real_label_over_placebo_weak_source_wins"
                ],
                placebo_over_real_training_labels_support_wins=placebo[
                    "placebo_over_real_label_weak_source_wins"
                ],
                shadow_reader_scored_matched_pairs=reader["scored_matched_answers"],
                shadow_reader_missing_or_unscorable=reader[
                    "missing_failed_or_unscorable"
                ],
                shadow_reader_mean_diagnostic_answer_f1_delta=reader[
                    "mean_paired_diagnostic_f1_delta"
                ],
                actual_reader_answer_bytes_changed=reader[
                    "actual_original_reader_answer_differences"
                ],
                semantic_citation_precision=None,
                independently_verified_benefit=False,
            )
    citations = sum(
        matrix_report["metrics"][f"48/{phase}/{ARMS[0]}"]["emitted_citation_markers"]
        for phase in PHASES
    )
    require(citations == 0, "frozen Reader emitted citation evidence unexpectedly")
    return dict(
        schema="hepta.stem-pinned-oct13-shadow-readout-audit.v1",
        source_sha=SOURCE,
        artifact_id=ARTIFACT_ID,
        six_arm_original_attempts=576,
        original_six_arm_top1_changes=original_arms,
        pairwise_head_source_only_choices=192,
        matched_objective_source_only_choices=384,
        placebo_source_only_choices=384,
        extra_shadow_reader_requests=32,
        independently_distinct_final_test_transfer_questions=16,
        final_test_transfer=final,
        frozen_48_citation_markers=citations,
        only_weak_native_document_support_compared=True,
        same_pretrained_reader_weights_prompt=True,
        no_prospective_independent_family_proof=True,
        independent_semantic_citation_precision=None,
        production_accepted=False,
    )


def audit_zip(path):
    arc = PinnedArchive(path, ZIP_SHA256)
    try:
        require(
            arc.read("tested-commit.txt").decode().strip() == SOURCE
            and arc.read("tested-tree.txt").decode().strip() == TREE,
            "source commit/tree differs from immutable hosted run",
        )
        result = audit_reports(
            arc.json("comparison/preregistered.json"),
            arc.jsonl("comparison/policy-predictions.jsonl"),
            arc.jsonl("comparison/pairwise-shadow-label-blind-choices.jsonl"),
            arc.jsonl("comparison/matched-objective-label-blind-choices.jsonl"),
            arc.jsonl("comparison/label-placebo-blind-choices.jsonl"),
            arc.json("comparison/pairwise-shadow-posthoc-source-support.json"),
            arc.json("comparison/matched-objective-posthoc-weak-source.json"),
            arc.json("comparison/label-placebo-posthoc-weak-source.json"),
            arc.json("comparison/pairwise-shadow-reader-review.json"),
            arc.json("comparison/report.json"),
        )
        result.update(
            zip_sha256=arc.sha256,
            sha256_manifest_entries=arc.manifest_entries,
            archived_original_model_calls_replayed=False,
        )
        return result
    finally:
        arc.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    report = audit_zip(args.archive)
    with args.output.open("x", encoding="utf-8") as dest:
        json.dump(
            report, dest, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        dest.write("\n")
    print(json.dumps(report, sort_keys=True, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
