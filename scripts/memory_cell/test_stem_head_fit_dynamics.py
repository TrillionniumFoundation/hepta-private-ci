"""Synthetically prove matched before/after Head learning measurements."""

import math
from types import SimpleNamespace as Obj
import unittest
from stem_head_fit_dynamics import compare_train_head_before_after as check


def inputs():
    qid = "train-1"
    feature = Obj(
        question_id=qid,
        family="family-A",
        candidate_ids=("A", "B"),
        seal=lambda: "feature-pinned",
    )
    row = Obj(features=feature, positive_indices=(0,))
    opts = dict(
        admitted_ids={"train-1"},
        stage=16,
        arm="gated",
        cell="general",
        previous_head_sha256="a" * 64,
        updated_head_sha256="b" * 64,
    )
    return (row,), [[0.0, 3.0, 0.0]], [[5.0, 3.0, 0.0]], opts


class TrainingDynamicsTests(unittest.TestCase):
    def test_true_before_after_training_loss_reduction(self):
        rows, before, after, opts = inputs()
        result = check(rows, before, after, **opts)
        self.assertLess(result["mean_weak_loss_delta"], 0)
        self.assertEqual(result["changed_train_top1_rows"], 1)
        self.assertTrue(result["objective_matches_actual_fit"])
        self.assertFalse(result["independent_generalization_established"])

    def test_identical_weights_do_not_forge_gain(self):
        rows, before, after, opts = inputs()
        x = check(rows, before, before, **opts)
        self.assertEqual(x["mean_weak_loss_delta"], 0.0)
        self.assertEqual(x["changed_train_top1_rows"], 0)
        self.assertEqual(x["improved_admitted_rows"], 0)

    def test_prototype_diagnostic_never_sgd_fit_optimization(self):
        rows, before, after, opts = inputs()
        opts["arm"] = "prototype"
        self.assertFalse(
            check(rows, before, after, **opts)["objective_matches_actual_fit"]
        )

    def test_null_class_and_single_candidate_do_not_fabricate_pair(self):
        rows, before, after, opts = inputs()
        feature = Obj(
            question_id="train-1",
            family="family-A",
            candidate_ids=("A",),
            seal=lambda: "feature-pinned",
        )
        row = Obj(features=feature, positive_indices=())
        result = check((row,), [[3.0, 0.0]], [[3.0, 2.0]], **opts)
        self.assertEqual(result["positive_negative_eligible_rows"], 0)
        self.assertEqual(result["annotated_null_rows"], 1)
        self.assertEqual(result["changed_train_top1_rows"], 0)

    def test_heldout_duplicate_nan_and_score_misalignment_fail_closed(self):
        rows, before, after, opts = inputs()
        bad = (
            ((rows[0], rows[0]), before * 2, after * 2, opts),
            (rows, before, after, dict(opts, admitted_ids={"heldout"})),
            (rows, before, [[math.nan, 3.0, 0.0]], opts),
            (rows, before, [[2.0, 3.0]], opts),
            (rows, before, after, dict(opts, previous_head_sha256="invalid")),
        )
        for i, (q, b, a, kw) in enumerate(bad):
            with self.subTest(case=i), self.assertRaises(ValueError):
                check(q, b, a, **kw)

    def test_loss_improvement_from_null_alone_does_not_change_source_ranking(self):
        rows, _, _, opts = inputs()
        before = [[0.0, 3.0, 8.0]]
        after = [[0.0, 3.0, -10.0]]
        receipt = check(rows, before, after, **opts)
        self.assertLess(receipt["mean_weak_loss_delta"], 0)
        self.assertEqual(receipt["changed_train_top1_rows"], 0)
        self.assertEqual(receipt["weak_source_top1_gains"], 0)
        self.assertEqual(receipt["pair_source_margin_improved_count"], 0)
        self.assertEqual(
            receipt["mean_positive_over_negative_candidate_margin_delta"], 0
        )
        self.assertLess(receipt["mean_null_over_best_candidate_delta"], 0)

    def test_source_rank_correction_is_counted_separately_from_loss(self):
        rows, before, after, opts = inputs()
        x = check(rows, before, after, **opts)
        self.assertEqual(x["pair_supervised_rows_with_support_top1_before"], 0)
        self.assertEqual(x["pair_supervised_rows_with_support_top1_after"], 1)
        self.assertEqual(x["weak_source_top1_gains"], 1)
        self.assertEqual(x["weak_source_top1_losses"], 0)
        self.assertEqual(x["pair_source_margin_improved_count"], 1)
        self.assertEqual(x["mean_positive_over_negative_candidate_margin_delta"], 5)

    def test_all_positive_or_abstaining_rows_have_no_contrastive_gain(self):
        rows, _, _, opts = inputs()
        feat = Obj(
            question_id="train-1",
            family="family-A",
            candidate_ids=("A", "B"),
            seal=lambda: "pinned",
        )
        all_positive = Obj(features=feat, positive_indices=(0, 1))
        result = check((all_positive,), [[2.0, 1.0, 0.0]], [[3.0, 1.0, 0.0]], **opts)
        self.assertEqual(result["positive_negative_eligible_rows"], 0)
        self.assertIsNone(result["mean_positive_over_negative_candidate_margin_delta"])
        self.assertEqual(result["weak_source_top1_gains"], 0)
        abstain = Obj(features=feat, positive_indices=())
        result2 = check((abstain,), [[2.0, 1.0, 0.0]], [[2.0, 1.0, 5.0]], **opts)
        self.assertEqual(result2["weak_source_top1_gains"], 0)
        self.assertEqual(result2["positive_negative_eligible_rows"], 0)
        self.assertFalse(result2["independent_generalization_established"])

    def test_nonfinite_margin_difference_fails_closed(self):
        rows, _, _, opts = inputs()
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            check(rows, [[1e308, -1e308, 0.0]], [[-1e308, 1e308, 0.0]], **opts)

    def test_weak_distractor_does_not_certify_a_hard_negative(self):
        rows, before, after, opts = inputs()
        result = check(rows, before, after, **opts)
        self.assertEqual(result["positive_negative_eligible_rows"], 1)
        self.assertIsNone(result["semantic_citation_precision"])


if __name__ == "__main__":
    unittest.main()
