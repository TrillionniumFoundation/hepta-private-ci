"""Synthetic audit fixtures do not stand in for the pinned Oct-13 model ZIP."""

import unittest

from stem_audit_archive import AuditError
from stem_oct13_shadow_result_audit import (
    ARMS,
    OBJECTIVES,
    KINDS,
    PHASES,
    SHADOWS,
    STAGES,
    SOURCE,
    audit_reports,
)


def fixture():
    questions = {"train": [f"train-{i}" for i in range(48)]}
    questions.update({p: [f"{p}-{i}" for i in range(8)] for p in PHASES})
    plan = dict(
        source_commit=SOURCE,
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
        questions=questions,
        arms=list(ARMS),
        curriculum_attempted_examples=list(STAGES),
    )
    policy, pairwise, objectives, placebo = [], [], [], []
    for stage in STAGES:
        for phase in PHASES:
            for qid in questions[phase]:
                for arm in ARMS:
                    policy.append(
                        dict(
                            stage=stage,
                            phase=phase,
                            question_id=qid,
                            arm=arm,
                            status="succeeded",
                            selected=0,
                            pool_digest="seal-" + qid,
                            family="family-" + qid,
                            receipt=dict(generator_parameter_updates=0),
                        )
                    )
                for arm in SHADOWS:
                    pairwise.append(
                        dict(
                            stage=stage,
                            phase=phase,
                            question_id=qid,
                            arm=arm,
                            status="succeeded",
                            actual_reader_calls=0,
                            training_labels_or_test_gold_in_answer=False,
                        )
                    )
                for kind in KINDS:
                    for objective in OBJECTIVES:
                        objectives.append(
                            dict(
                                stage=stage,
                                phase=phase,
                                question_id=qid,
                                kind=kind,
                                objective=objective,
                                status="succeeded",
                            )
                        )
                    for label in ("true", "shuffled"):
                        placebo.append(
                            dict(
                                stage=stage,
                                phase=phase,
                                question_id=qid,
                                kind=kind,
                                condition=label,
                                status="succeeded",
                            )
                        )

    pair_summary = {}
    objective_summary = {}
    placebo_summary = {}
    for stage in STAGES:
        for phase in PHASES:
            for arm in SHADOWS:
                pair_summary[f"{stage}/{phase}/{arm}"] = dict(
                    attempted=8,
                    source_label_scored=8,
                    source_label_unresolved_or_failure=0,
                    selection_changed=0,
                    native_weak_support_gains=0,
                    native_weak_support_regressions=0,
                )
            for kind in KINDS:
                objective_summary[f"{stage}/{phase}/{kind}"] = dict(
                    attempted=8,
                    native_weak_source_scored=8,
                    unscored_or_failed=0,
                    pairwise_over_ce_weak_source_gains=0,
                    ce_over_pairwise_weak_source_gains=0,
                )
                placebo_summary[f"{stage}/{phase}/{kind}"] = dict(
                    attempted=8,
                    weak_source_scored=8,
                    failed_or_unresolved=0,
                    real_label_over_placebo_weak_source_wins=0,
                    placebo_over_real_label_weak_source_wins=0,
                )
    pair_report = dict(
        total_label_blind_decisions=192,
        observed_reader_calls=0,
        production_accepted=False,
        independently_established_generalization=False,
        by_checkpoint_phase_arm=pair_summary,
    )
    objective_report = dict(
        label_blind_shadow_decisions=384,
        fitted_objective_checkpoints=24,
        training_questions_same_for_both_objectives=True,
        initial_head_weights_identical=True,
        no_original_policy_or_reader_mutation=True,
        production_accepted=False,
        by_stage_phase_kind=objective_summary,
    )
    placebo_report = dict(
        sealed_choices=384,
        trained_heads=24,
        production_accepted=False,
        by_stage_phase_kind=placebo_summary,
    )
    reader_report = dict(
        planned_reader_controls=32,
        same_fixed_reader_weights_prompt_generation=True,
        original_576_policy_answers_unchanged=True,
        production_accepted=False,
        independent_prospective_generalization=False,
        per_phase_arm={
            f"{phase}/{arm}": dict(
                attempted=8,
                scored_matched_answers=8,
                missing_failed_or_unscorable=0,
                source_changed=0,
                semantic_citation_precision=None,
                independent_source_entailment_judged=False,
                mean_paired_diagnostic_f1_delta=0.0,
                actual_original_reader_answer_differences=0,
            )
            for phase in ("test", "transfer")
            for arm in SHADOWS
        },
    )
    report = dict(
        census=dict(planned=576, recorded=576, complete=True),
        production_accepted=False,
        semantic_citation_precision=None,
        metrics={
            f"48/{phase}/frozen_rerank": {"emitted_citation_markers": 0}
            for phase in PHASES
        },
    )
    return (
        plan,
        policy,
        pairwise,
        objectives,
        placebo,
        pair_report,
        objective_report,
        placebo_report,
        reader_report,
        report,
    )


class PinnedShadowAuditTests(unittest.TestCase):
    def test_full_synthetic_census_is_nonqualifying(self):
        x = audit_reports(*fixture())
        self.assertEqual(x["six_arm_original_attempts"], 576)
        self.assertEqual(x["pairwise_head_source_only_choices"], 192)
        self.assertEqual(x["matched_objective_source_only_choices"], 384)
        self.assertEqual(x["extra_shadow_reader_requests"], 32)
        self.assertEqual(x["independently_distinct_final_test_transfer_questions"], 16)
        self.assertFalse(x["production_accepted"])
        self.assertFalse(
            x["final_test_transfer"]["test"]["linear"]["independently_verified_benefit"]
        )

    def test_real_net_source_gain_is_separate_from_reader_f1(self):
        row = fixture()
        row[5]["by_checkpoint_phase_arm"]["48/test/pairwise_linear"].update(
            selection_changed=1,
            native_weak_support_gains=1,
        )
        row[8]["per_phase_arm"]["test/pairwise_linear"].update(
            source_changed=1,
            mean_paired_diagnostic_f1_delta=-0.25,
            actual_original_reader_answer_differences=1,
        )
        x = audit_reports(*row)["final_test_transfer"]["test"]["linear"]
        self.assertEqual(x["pairwise_weak_native_support_gains"], 1)
        self.assertEqual(x["shadow_reader_mean_diagnostic_answer_f1_delta"], -0.25)
        self.assertFalse(x["independently_verified_benefit"])

    def test_duplicate_policy_and_missing_shadow_are_rejected(self):
        for mode in (
            "duplicate policy",
            "missing pairwise",
            "missing objective",
            "missing placebo",
        ):
            row = fixture()
            if mode == "duplicate policy":
                row[1][-1] = dict(row[1][0])
            elif mode == "missing pairwise":
                row[2].pop()
            elif mode == "missing objective":
                row[3].pop()
            else:
                row[4].pop()
            with self.subTest(mode=mode), self.assertRaises(AuditError):
                audit_reports(*row)

    def test_inconsistent_8_case_denominators_reject(self):
        for index, field in (
            (5, "source_label_scored"),
            (6, "native_weak_source_scored"),
            (7, "weak_source_scored"),
            (8, "scored_matched_answers"),
        ):
            row = fixture()
            field_key = (
                "by_checkpoint_phase_arm"
                if index == 5
                else "by_stage_phase_kind"
                if index in (6, 7)
                else "per_phase_arm"
            )
            first = next(iter(row[index][field_key].values()))
            first[field] = 9
            with self.subTest(index=index), self.assertRaises(AuditError):
                audit_reports(*row)

    def test_reader_semantic_precision_cannot_be_forged(self):
        row = fixture()
        row[8]["per_phase_arm"]["test/pairwise_linear"][
            "semantic_citation_precision"
        ] = 1.0
        with self.assertRaises(AuditError):
            audit_reports(*row)

    def test_reader_changed_weights_or_protocol_reject(self):
        row = fixture()
        row[8]["same_fixed_reader_weights_prompt_generation"] = False
        with self.assertRaises(AuditError):
            audit_reports(*row)

    def test_forged_native_citation_or_production_acceptance_rejected(self):
        row = fixture()
        row[9]["metrics"]["48/test/frozen_rerank"]["emitted_citation_markers"] = 1
        with self.assertRaises(AuditError):
            audit_reports(*row)
        row = fixture()
        row[9]["production_accepted"] = True
        with self.assertRaises(AuditError):
            audit_reports(*row)


if __name__ == "__main__":
    unittest.main()
