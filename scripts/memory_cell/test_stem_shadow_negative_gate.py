"""Synthetic negative-gate tampering fixtures; not semantic or task evidence."""

from copy import deepcopy
import unittest

from stem_shadow_negative_gate import (
    ARMS,
    CELLS,
    PHASES,
    STAGES,
    SHADOW_GRID,
    audit_shadow,
)
from stem_audit_archive import AuditError


def fixture():
    questions = {"train": [f"train-{n}" for n in range(48)]}
    questions.update({p: [f"{p}-{n}" for n in range(8)] for p in PHASES})
    routes = {
        qid: CELLS[n % 2] for p in questions for n, qid in enumerate(questions[p])
    }
    plan = dict(
        questions=questions,
        routes=routes,
        curriculum_attempted_examples=list(STAGES),
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
    )
    calibrations = []
    for st in STAGES:
        for arm in ARMS:
            for cell in CELLS:
                calibrations.append(
                    dict(
                        stage=st,
                        arm=arm,
                        cell=cell,
                        status="succeeded",
                        role="nonqualifying-train-only-shadow-scale",
                        checkpoint_head_sha256="a" * 64,
                        receipt=dict(
                            stage=st,
                            arm=arm,
                            cell=cell,
                            scale_grid=list(SHADOW_GRID),
                            chosen_scale=8.0 if arm != "prototype" else 0.0,
                            winner_chosen_from_train_only=True,
                            all_test_and_transfer_answers_and_labels_unseen=True,
                            no_new_reader_call=True,
                            production_accepted=False,
                        ),
                    )
                )
    decision = []
    report = {}
    for st in STAGES:
        for arm in ARMS:
            for cell in CELLS:
                for phase in PHASES:
                    count = 0
                    for qid in questions[phase]:
                        if routes[qid] != cell:
                            continue
                        decision.append(
                            dict(
                                stage=st,
                                arm=arm,
                                cell=cell,
                                phase=phase,
                                question_id=qid,
                                role="shadow-source-only-no-Reader-execution",
                                status="succeeded",
                                chosen_scale=8.0 if arm != "prototype" else 0.0,
                                head_sha256="a" * 64,
                                actual_reader_executions=0,
                                native_targets_unread=True,
                                selected_index=0,
                                frozen_index=0,
                                selected_source_id=qid + ":source",
                                original_pool_digest="b" * 64,
                            )
                        )
                        count += 1
                    report[f"{st}/{arm}/{cell}/{phase}"] = dict(
                        planned=count,
                        successful_choices=count,
                        failed_choices=0,
                        source_scored=count,
                        changed_source_top1=0,
                        shadow_weak_source_gains=0,
                        shadow_weak_source_regressions=0,
                        semantic_entailment_judged=False,
                        reader_called_for_shadow=False,
                    )
    provenance = dict(
        source_choices_verified=480,
        planned_shadow_source_choices=480,
        planned_shadow_calibrations=30,
        no_gold_target_read=True,
        no_additional_reader_call=True,
        production_accepted=False,
    )
    post = dict(
        planned_shadow_choices=480,
        results=report,
        labels_opened_only_after_all_model_decisions=True,
        production_accepted=False,
    )
    return plan, calibrations, decision, provenance, post


class NegativeGateTests(unittest.TestCase):
    def test_actual_subject_census_and_all_negative_decisions(self):
        data = audit_shadow(*fixture())
        self.assertEqual(data["actual_choice_census"], 480)
        self.assertEqual(data["actual_training_calibrations"], 30)
        self.assertEqual(len(data["by_stage_arm"]), 15)
        self.assertEqual(len(data["final_checkpoint_rejected_arms"]), 5)
        self.assertTrue(data["none_of_five_arms_qualified_for_shadow_reader_at_48"])
        self.assertFalse(data["production_accepted"])

    def test_one_better_test_without_better_transfer_does_not_pass(self):
        plan, cal, decisions, provenance, report = fixture()
        row = next(
            x
            for x in decisions
            if (x["stage"], x["arm"], x["phase"]) == (48, "gated", "test")
        )
        row["selected_index"] = 1
        label = report["results"][f"48/gated/{row['cell']}/test"]
        label["changed_source_top1"] = 1
        label["shadow_weak_source_gains"] = 1
        data = audit_shadow(plan, cal, decisions, provenance, report)
        self.assertTrue(data["by_stage_arm"]["48/gated"]["source_only_rejection"])
        self.assertEqual(
            data["by_stage_arm"]["48/gated"]["heldout_test"][
                "shadow_weak_source_gains"
            ],
            1,
        )

    def test_hypothetical_two_phase_improvement_is_still_not_semantic_approval(self):
        plan, cal, decisions, provenance, report = fixture()
        for phase in ("test", "transfer"):
            row = next(
                x
                for x in decisions
                if (x["stage"], x["arm"], x["phase"]) == (48, "gated", phase)
            )
            row["selected_index"] = 1
            label = report["results"][f"48/gated/{row['cell']}/{phase}"]
            label["changed_source_top1"] = 1
            label["shadow_weak_source_gains"] = 1
        result = audit_shadow(plan, cal, decisions, provenance, report)
        gated = result["by_stage_arm"]["48/gated"]
        self.assertFalse(gated["source_only_rejection"])
        self.assertFalse(gated["production_accepted"])
        self.assertIsNone(result["semantic_citation_precision"])

    def test_hidden_heldout_or_new_reader_is_rejected(self):
        for field, value in (
            ("native_targets_unread", False),
            ("actual_reader_executions", 1),
            ("chosen_scale", 64.0),
            ("head_sha256", "c" * 64),
        ):
            data = fixture()
            data[2][0][field] = value
            with self.subTest(field=field), self.assertRaises(AuditError):
                audit_shadow(*data)

    def test_duplicate_missing_and_forged_source_choice_rejected(self):
        for mode in ("duplicate", "missing", "forged"):
            plan, fit, rows, prov, post = fixture()
            if mode == "duplicate":
                rows[-1] = deepcopy(rows[0])
            elif mode == "missing":
                rows.pop()
            else:
                rows[0]["selected_index"] = 1
            with self.subTest(mode=mode), self.assertRaises((AuditError, ValueError)):
                audit_shadow(plan, fit, rows, prov, post)

    def test_missing_train_scale_or_label_before_choice_rejected(self):
        plan, fits, rows, prov, post = fixture()
        fits.pop()
        with self.assertRaises(AuditError):
            audit_shadow(plan, fits, rows, prov, post)
        plan, fits, rows, prov, post = fixture()
        post["labels_opened_only_after_all_model_decisions"] = False
        with self.assertRaises(AuditError):
            audit_shadow(plan, fits, rows, prov, post)

    def test_gold_gain_cannot_exceed_actual_source_choice_changes(self):
        plan, fits, rows, prov, post = fixture()
        post["results"]["48/gated/general/test"]["shadow_weak_source_gains"] = 1
        with self.assertRaises(AuditError):
            audit_shadow(plan, fits, rows, prov, post)


if __name__ == "__main__":
    unittest.main()
