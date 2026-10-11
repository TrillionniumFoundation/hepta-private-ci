"""Source-pinned, read-only decision gate for a completed STRICT native matrix.

No model execution, optimizer, Reader call, hyperparameter selection, label
change or production promotion. The 16 final test/transfer questions, not
their 48 repeats across checkpoints, are the unit of analysis.
"""

import argparse
import json
from pathlib import Path

from stem_audit_archive import PinnedArchive, require
from stem_native_reader_stratification import stratify_original_reader
from stem_native_oracle_reader_capacity import reference_reader_capacity

SOURCE = "cb9e98365b5f46e00fb2693f548a7215b1ed1145"
TREE = "022c9aa8abc095c91ef744644329aaed12564859"
ZIP_SHA = "be3393f448993451c7860e8867e28a79f5fb7f95d5773f79ed55b30d12a84776"
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


def _index(plan, rows):
    expected = {
        (stage, phase, qid, arm)
        for stage in STAGES
        for phase in PHASES
        for qid in plan["questions"][phase]
        for arm in ARMS
    }
    actual = {}
    for row in rows:
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        require(
            key in expected and key not in actual,
            "duplicate/unknown original policy row",
        )
        require(
            row["status"] in ("succeeded", "failed"), "unknown original policy status"
        )
        actual[key] = row
    require(
        len(actual) == len(expected) == 576,
        "strict complete 576-record original policy census required",
    )
    return actual


def evaluate_strict_run(plan, raw, scored, report, ceiling):
    registered = [q for p in ("train", *PHASES) for q in plan["questions"][p]]
    require(
        tuple(plan["arms"]) == ARMS
        and tuple(plan["curriculum_attempted_examples"]) == STAGES
        and len(plan["questions"]["train"]) == 48
        and all(len(plan["questions"][p]) == 8 for p in PHASES)
        and len(set(registered)) == len(registered) == 80
        and set(plan["routes"]) == set(registered)
        and set(plan["question_families"]) == set(registered)
        and plan["source_visibility_policy"]
        == "strict-as-of-before-index-and-every-Encoder-v1"
        and report["plan"] == plan
        and report["production_accepted"] is False
        and report["semantic_citation_precision"] is None,
        "registered cohort, strict chronology or nonproduction gate drift",
    )
    orig, graded = _index(plan, raw), _index(plan, scored)
    require(
        all(x["status"] == "succeeded" for x in orig.values()),
        "this pinned run is not 576/576 execution complete",
    )
    for key, before in orig.items():
        after = graded[key]
        require(
            all(after.get(k) == v for k, v in before.items()),
            "posthoc scoring changed an original policy answer/receipt",
        )
        require(after["status"] == before["status"], "posthoc policy status changed")
    reader = report["reader"]
    require(
        report["logical_policy_attempts"] == 576
        and reader["actual_attempts"] == 48
        and reader["actual_successes"] == 48
        and reader["actual_failed_attempts"] == 0
        and reader["cache_hits"] == 543,
        "pinned model Reader invocation accounting changed: "
        + json.dumps(
            dict(
                expected=dict(
                    actual_attempts=48,
                    actual_successes=48,
                    actual_failed_attempts=0,
                    cache_hits=543,
                ),
                observed={
                    k: reader.get(k)
                    for k in (
                        "actual_attempts",
                        "actual_successes",
                        "actual_failed_attempts",
                        "cache_hits",
                    )
                },
            ),
            sort_keys=True,
        ),
    )
    require(
        report["no_evidence_reader_report"]["planned_controls"] == 32,
        "control reader census is missing",
    )
    require(
        report["no_evidence_reader_call_accounting"]["policy_and_oracle_reader"][
            "actual_attempts"
        ]
        == reader["actual_attempts"],
        "post-policy Oracle versus independent no-evidence Reader mixed",
    )
    require(
        len(report["within_head_train_fit"]) == 30,
        "actual persistent Head before/after receipts missing",
    )

    observed = ceiling["decisions"]
    expected_keys = {(p, q) for p in PHASES for q in plan["questions"][p]}
    labelled = {}
    for row in observed:
        key = (row["phase"], row["question_id"])
        require(
            key in expected_keys and key not in labelled,
            "duplicate/missing source-coverage judgment",
        )
        require(
            row["source_family"] == plan["question_families"][key[1]],
            "retrospective source-family substitution",
        )
        require(
            row["native_weak_support_not_window_entailment"] is True
            and row["independently_reviewed_source_sufficiency"] is False,
            "native support promoted to semantic entailment",
        )
        labelled[key] = row
    require(
        set(labelled) == expected_keys and len(labelled) == 32,
        "source ceiling omitted a preregistered evaluation question",
    )
    answerable = [x for x in labelled.values() if x["weak_native_support_resolved"]]
    unanswerable = [x for x in labelled.values() if x["native_source_unanswerable"]]
    unresolved = [
        x
        for x in labelled.values()
        if not x["weak_native_support_resolved"] and not x["native_source_unanswerable"]
    ]
    require(
        not unresolved and len(answerable) == 25 and len(unanswerable) == 7,
        "exact published answerability denominator changed",
    )
    available = sum(x["native_support_available_in_pool"] is True for x in answerable)
    absent = sum(x["native_support_available_in_pool"] is False for x in answerable)
    require(available + absent == 25, "unobserved candidate pool falsely filled")

    comparisons, phase_results = {}, {}
    for arm in ARMS[1:]:
        per_stage = {}
        for stage in STAGES:
            by_phase = {}
            for phase in PHASES:
                same, changed_answer, changed_source = 0, 0, 0
                support_gains, support_losses, ablation = 0, 0, 0
                for qid in plan["questions"][phase]:
                    key = stage, phase, qid
                    frozen = orig[(*key, ARMS[0])]
                    learned = orig[(*key, arm)]
                    native = labelled[phase, qid]
                    require(
                        frozen["status"] == learned["status"] == "succeeded"
                        and frozen["family"] == learned["family"]
                        and frozen["cell"] == learned["cell"] == plan["routes"][qid]
                        and frozen["pool_digest"] == learned["pool_digest"]
                        and frozen["receipt"]["generator_identity"]
                        == learned["receipt"]["generator_identity"]
                        and frozen["receipt"]["generator_profile"]
                        == learned["receipt"]["generator_profile"],
                        "cross-arm source, Reader, Cell, or status binding changed",
                    )
                    same += 1
                    changed_answer += frozen["answer"] != learned["answer"]
                    changed_source += frozen["selected"] != learned["selected"]
                    if native["weak_native_support_resolved"]:
                        prior = graded[(*key, ARMS[0])]["source_choice_correct"]
                        after = graded[(*key, arm)]["source_choice_correct"]
                        require(
                            type(prior) is int
                            and type(after) is int
                            and prior in (0, 1)
                            and after in (0, 1),
                            "answerable weak-source choice missing or altered",
                        )
                        if (
                            stage == 48
                            and native["frozen_selected_native_support"] is not None
                        ):
                            require(
                                prior == int(native["frozen_selected_native_support"]),
                                "frozen source correctness disagrees with independent pool census",
                            )
                        if frozen["selected"] == learned["selected"]:
                            require(
                                prior == after,
                                "identical evidence choice was rescored as a gain",
                            )
                        support_gains += after > prior
                        support_losses += after < prior
                    else:
                        ablation += 1
                by_phase[phase] = dict(
                    planned=same,
                    changed_original_reader_answer_bytes=changed_answer,
                    changed_selected_source=changed_source,
                    native_document_support_gains=support_gains,
                    native_document_support_regressions=support_losses,
                    native_unanswerable_held_separate=ablation,
                    native_entailment_independently_verified=False,
                )
            per_stage[str(stage)] = by_phase
        comparisons[arm] = per_stage
        phase_results[arm] = {p: per_stage["48"][p] for p in ("test", "transfer")}
    unique_heldout = set(plan["questions"]["test"]) | set(plan["questions"]["transfer"])
    families = {plan["question_families"][q] for q in unique_heldout}
    require(
        len(unique_heldout) == 16 and len(families) == 3,
        "held-out repeated question/family count changed",
    )
    final_qualified = {
        arm: all(
            phase_results[arm][p]["native_document_support_gains"]
            > phase_results[arm][p]["native_document_support_regressions"]
            for p in ("test", "transfer")
        )
        for arm in ARMS[1:]
    }
    return dict(
        schema="hepta.stem-current-strict-source-outcome-audit.v1",
        source=SOURCE,
        recorded_policy_attempts=576,
        successful_policy_attempts=576,
        unique_test_transfer_questions=16,
        distinct_native_test_transfer_source_families=3,
        repeated_evaluation_checkpoints=STAGES,
        answerable_evaluation_questions=25,
        native_unanswerable_evaluation_questions=7,
        answerable_native_support_in_fixed_pool=available,
        answerable_native_support_absent_from_fixed_pool=absent,
        actual_reader_attempts=reader["actual_attempts"],
        actual_reader_successes=reader["actual_successes"],
        main_reader_calls_include_postpolicy_oracle_diagnostics=True,
        six_arm_checkpoint_48_reader_attempts=33,
        independent_no_evidence_reader_charged_separately=True,
        actual_reader_cache_hits=reader["cache_hits"],
        by_arm_checkpoint_phase=comparisons,
        final_test_transfer_comparison=phase_results,
        any_arm_positive_on_both_test_and_transfer=any(final_qualified.values()),
        requires_independent_semantic_evaluation=True,
        independently_reviewed_entailment=False,
        semantic_citation_precision=None,
        production_accepted=False,
    )


def audit_zip(path):
    archive = PinnedArchive(Path(path), ZIP_SHA)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == SOURCE,
            "source commit is not the pinned strict run",
        )
        require(
            archive.read("tested-tree.txt").decode().strip() == TREE,
            "source tree is not the pinned strict run",
        )
        plan = archive.json("comparison/preregistered.json")
        original = archive.jsonl("comparison/policy-predictions.jsonl")
        scored = archive.json("comparison/scored-policy-attempts.json")
        report = archive.json("comparison/report.json")
        ceiling = archive.json("comparison/post-policy-native-source-ceiling.json")
        result = evaluate_strict_run(plan, original, scored, report, ceiling)
        result["reader_effect_by_original_source_coverage"] = stratify_original_reader(
            plan,
            original,
            ceiling,
            archive.jsonl("comparison/reader-no-evidence.jsonl"),
            report["matched_frozen_vs_no_evidence"],
        )
        # All oracle and zero-context raw answers were produced by the original
        # immutable model run. The answer-dependent literal span cannot be
        # promoted to human-reviewed sufficient evidence or a trained policy.
        result["answer_literal_oracle_reader_diagnostic"] = reference_reader_capacity(
            plan,
            scored,
            archive.jsonl("comparison/oracle-diagnostic.jsonl"),
            archive.jsonl("comparison/reader-no-evidence.jsonl"),
            report["no_evidence_reader_report"],
            ceiling,
        )
        result["artifact_zip_sha256"] = archive.sha256
        result["verified_manifest_entries"] = archive.manifest_entries
        return result
    finally:
        archive.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = audit_zip(args.archive)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
