"""Synthetic complete 576-case bridge; no native benchmark gains are fabricated."""

import unittest

from stem_train_heldout_bridge import train_to_heldout_gap

ARMS = ("frozen_rerank", "prototype", "linear", "gated",
        "lineage_lora_gated", "independent_lora_gated")
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
CELLS = ("general", "temporal")


def fixture():
    questions = {"train": [f"train-{i}" for i in range(48)]}
    questions.update({
        phase: [f"{phase}-{i}" for i in range(8)] for phase in PHASES
    })
    routes = {q: CELLS[i % 2] for group in questions.values()
              for i, q in enumerate(group)}
    plan = dict(
        questions=questions, routes=routes,
        arms=list(ARMS), curriculum_attempted_examples=list(STAGES),
        cells=list(CELLS),
    )
    scored = []
    for stage in STAGES:
        for phase in PHASES:
            for qid in questions[phase]:
                for arm in ARMS:
                    scored.append(dict(
                        stage=stage, phase=phase, question_id=qid, arm=arm,
                        status="succeeded", cell=routes[qid],
                        family="native-family-" + qid,
                        selected=0,
                        pool_digest="sealed-" + qid,
                        source_choice_correct=0,
                        diagnostic_answer_f1=0.25,
                        answer="fixture answer",
                    ))
    learning = []
    for stage in STAGES:
        for arm in ARMS:
            for cell in CELLS:
                h = dict(
                    stage=stage, arm=arm, cell=cell,
                    status="succeeded", before_sha256="a"*64,
                    after_sha256="b"*64,
                )
                if arm != "frozen_rerank":
                    h["within_train_fit_dynamics"] = dict(
                        checkpoint=stage, arm=arm, cell=cell,
                        previous_head_sha256=h["before_sha256"],
                        updated_head_sha256=h["after_sha256"],
                        heldout_annotations_consulted=False,
                        independent_generalization_established=False,
                        production_accepted=False,
                        mean_weak_loss_delta=-0.4,
                        weak_source_top1_gains=1,
                        mean_positive_over_negative_candidate_margin_delta=2.0,
                    )
                learning.append(h)
    return plan, learning, scored


class GeneralizationBridgeTests(unittest.TestCase):
    def test_complete_census_preserves_training_vs_test_distinction(self):
        plan, learning, scored = fixture()
        result = train_to_heldout_gap(plan, learning, scored)
        self.assertEqual(result["planned_source_policy_rows"], 576)
        self.assertEqual(len(result["by_checkpoint_cell_arm"]), 30)
        arm = result["by_checkpoint_cell_arm"]["48/gated/general"]
        self.assertLess(arm["within_head_train_mean_weak_loss_delta"], 0)
        self.assertEqual(arm["phases"]["test"]["planned"], 4)
        self.assertEqual(arm["phases"]["transfer"]["planned"], 4)
        self.assertTrue(arm["train_fit_but_no_heldout_native_source_net_gain"])
        self.assertFalse(arm["authentic_independent_generalization"])
        self.assertFalse(result["production_accepted"])

    def test_one_heldout_supported_selection_gain_is_not_fabricated_for_other_arms(self):
        plan, learning, scored = fixture()
        changed = next(
            row for row in scored if row["stage"] == 48
            and row["phase"] == "test" and row["question_id"] == "test-0"
            and row["arm"] == "gated"
        )
        changed["selected"] = 1
        changed["source_choice_correct"] = 1
        changed["diagnostic_answer_f1"] = 0.75
        result = train_to_heldout_gap(plan, learning, scored)
        gated = result["by_checkpoint_cell_arm"]["48/gated/general"]
        self.assertEqual(gated["phases"]["test"]["native_support_gains"], 1)
        self.assertEqual(gated["phases"]["test"]["source_decision_changes"], 1)
        self.assertAlmostEqual(
            gated["phases"]["test"]["paired_reader_f1_delta_mean"], 0.125
        )
        self.assertFalse(gated["train_fit_but_no_heldout_native_source_net_gain"])
        other = result["by_checkpoint_cell_arm"]["48/linear/general"]
        self.assertEqual(other["phases"]["test"]["native_support_gains"], 0)
        self.assertFalse(gated["authentic_independent_generalization"])

    def test_reader_failure_does_not_erase_observed_selector_choice(self):
        plan, learning, scored = fixture()
        x = next(row for row in scored if row["stage"] == 48
                 and row["phase"] == "test" and row["question_id"] == "test-0"
                 and row["arm"] == "gated")
        x["status"] = "failed"
        x.pop("diagnostic_answer_f1")
        x["source_choice_correct"] = 1
        x["selected"] = 1
        result = train_to_heldout_gap(plan, learning, scored)
        summary = result["by_checkpoint_cell_arm"]["48/gated/general"]["phases"]["test"]
        self.assertEqual(summary["source_compared"], 4)
        self.assertEqual(summary["native_support_gains"], 1)
        self.assertEqual(summary["reader_f1_scored"], 3)
        self.assertEqual(summary["reader_f1_unscored"], 1)
        self.assertEqual(summary["all_planned_reader_f1_delta_bounds"], [-0.25, 0.25])

    def test_unresolved_native_support_keeps_original_question_in_denominator(self):
        plan, learning, scored = fixture()
        for row in scored:
            if (row["stage"], row["phase"], row["question_id"]) == (
                48, "transfer", "transfer-0"
            ):
                row["source_choice_correct"] = None
        result = train_to_heldout_gap(plan, learning, scored)
        summary = result["by_checkpoint_cell_arm"]["48/gated/general"]["phases"]["transfer"]
        self.assertEqual(summary["planned"], 4)
        self.assertEqual(summary["source_compared"], 3)
        self.assertEqual(summary["source_unresolved_or_unselected"], 1)

    def test_retrieval_pool_identity_and_family_mismatch_fail(self):
        for field, value in (
            ("pool_digest", "changed-pool"),
            ("family", "wrong-family"),
            ("cell", "opposite-cell"),
        ):
            plan, learning, scored = fixture()
            candidate = next(
                x for x in scored if x["stage"] == 16
                and x["phase"] == "test" and x["question_id"] == "test-0"
                and x["arm"] == "gated"
            )
            candidate[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                train_to_heldout_gap(plan, learning, scored)

    def test_missing_or_duplicate_policy_or_head_fails_closed(self):
        for corruption in ("missing-policy", "duplicate-policy", "missing-head"):
            plan, learning, scored = fixture()
            if corruption == "missing-policy":
                scored.pop()
            elif corruption == "duplicate-policy":
                scored[-1] = dict(scored[0])
            else:
                learning.pop()
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                train_to_heldout_gap(plan, learning, scored)

    def test_head_sha_or_hidden_heldout_annotation_claim_is_rejected(self):
        for corruption in ("sha", "label"):
            plan, learning, scored = fixture()
            head = next(x for x in learning if x["arm"] == "gated")
            probe = head["within_train_fit_dynamics"]
            if corruption == "sha":
                probe["previous_head_sha256"] = "c" * 64
            else:
                probe["heldout_annotations_consulted"] = True
            with self.subTest(corruption=corruption), self.assertRaisesRegex(
                ValueError, "TRAIN-only"
            ):
                train_to_heldout_gap(plan, learning, scored)


if __name__ == "__main__":
    unittest.main()
