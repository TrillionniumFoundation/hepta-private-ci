"""Weak training objective probes do not evaluate held-out task quality."""

import math
import unittest

from stem_cell_training_probe import train_probe, summarize_train_probes


class TrainingProbeTests(unittest.TestCase):
    def test_correct_source_logit_gain_reduces_training_loss(self):
        probe = train_probe([0.0, 2.0, 0.0], [5.0, 2.0, 0.0], (0,), fit_strategy="sgd")
        self.assertLess(probe["loss_delta"], 0)
        self.assertTrue(probe["weak_label_loss_improved"])
        self.assertLess(probe["native_margin"], 0)
        self.assertGreater(probe["learned_margin"], 0)
        self.assertTrue(probe["weak_source_support_not_entailment"])
        self.assertFalse(probe["usable_as_independent_generalization_evidence"])

    def test_unchanged_logits_show_no_fake_training_gain(self):
        probe = train_probe([2.0, 1.0, 0.0], [2.0, 1.0, 0.0], (0,), fit_strategy="sgd")
        self.assertEqual(probe["loss_delta"], 0.0)
        self.assertFalse(probe["weak_label_loss_improved"])

    def test_multiple_supports_are_multi_positive_not_collapsed(self):
        single = train_probe([1.0, 4.0, -1.0, 0.0],
                             [1.0, 4.0, -1.0, 0.0], (0,), fit_strategy="sgd")
        many = train_probe([1.0, 4.0, -1.0, 0.0],
                           [1.0, 4.0, -1.0, 0.0], (0, 1), fit_strategy="sgd")
        self.assertLess(many["frozen_weak_label_loss"], single["frozen_weak_label_loss"])
        self.assertEqual(many["supported_candidate_count"], 2)

    def test_annotated_unanswerable_does_not_create_fake_evidence_positive(self):
        original = train_probe([2.0, 1.0, 0.0], [2.0, 1.0, 0.0], (), fit_strategy="sgd")
        learned = train_probe([2.0, 1.0, 0.0], [2.0, 1.0, 4.0], (), fit_strategy="sgd")
        self.assertTrue(original["annotated_unanswerable"])
        self.assertLess(learned["learned_weak_label_loss"],
                        original["frozen_weak_label_loss"])
        self.assertEqual(original["supported_candidate_count"], 0)

    def test_no_candidate_still_has_only_null_class(self):
        probe = train_probe([0.0], [0.0], (), fit_strategy="sgd")
        self.assertEqual(probe["candidate_count"], 0)
        self.assertEqual(probe["frozen_weak_label_loss"], 0.0)
        self.assertIsNone(probe["native_margin"])

    def test_invalid_heldout_or_nonfinite_logits_cannot_sneak_in(self):
        for original, learned, pos in (
            ([1.0, 0.0], [1.0, 0.0], (1,)),
            ([1.0, 0.0], [1.0, 0.0], (0, 0)),
            ([1.0, 0.0], [1.0] , (0,)),
            ([1.0, math.nan], [1.0, 0.0] , (0,)),
            ([1.0, 0.0], [1.0, math.inf], (0,)),
        ):
            with self.subTest(pos=pos), self.assertRaises(ValueError):
                train_probe(original, learned, pos, fit_strategy="sgd")

    def test_complete_failure_census_preserves_all_attempted_probes(self):
        good = train_probe([1.0, 0.0], [2.0, 0.0], (0,), fit_strategy="sgd")
        records = [
            dict(stage=16, arm="gated", cell="general", question_id="q1", status="succeeded",
                 probe=good),
            dict(stage=16, arm="gated", cell="general", question_id="q2", status="failed"),
        ]
        summary = summarize_train_probes(records)["16/gated/general"]
        self.assertEqual(summary["attempted"], 2)
        self.assertEqual(summary["probe_failed"], 1)
        self.assertEqual(summary["objective_aligned_lower_than_frozen"], 1)
        self.assertFalse(summary["generalization_claim"])


    def test_prototype_loss_is_diagnostic_not_sgd(self):
        p = train_probe([0.0, 3.0, 0.0], [4.0, 3.0, 0.0], (0,),
                        fit_strategy="prototype")
        self.assertTrue(p["weak_label_loss_improved"])
        self.assertFalse(p["objective_matches_head_fit"])
        records = [dict(stage=16, arm="prototype", cell="general",
                        question_id="q1", status="succeeded", probe=p)]
        totals = summarize_train_probes(records)["16/prototype/general"]
        self.assertEqual(totals["objective_aligned_lower_than_frozen"], 0)
        self.assertEqual(totals["lower_diagnostic_loss_than_frozen"], 1)

    def test_frozen_control_cannot_claim_update(self):
        original = [3.0, 2.0, 0.0]
        p = train_probe(original, original, (0,), fit_strategy="frozen")
        self.assertFalse(p["objective_matches_head_fit"])
        with self.assertRaises(ValueError):
            train_probe(original, [4.0, 2.0, 0.0], (0,),
                        fit_strategy="frozen")

    def test_sgd_without_candidates_has_no_optimizer_update(self):
        p = train_probe([0.0], [0.0], (), fit_strategy="sgd")
        self.assertTrue(p["no_candidate_sgd_step"])
        self.assertFalse(p["objective_matches_head_fit"])

    def test_duplicate_and_wrong_arm_strategy_are_rejected(self):
        p = train_probe([2.0, 0.0], [3.0, 0.0], (0,),
                        fit_strategy="sgd")
        row = dict(stage=16, arm="linear", cell="general",
                   question_id="q1", status="succeeded", probe=p)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            summarize_train_probes([row, dict(row)])
        with self.assertRaisesRegex(ValueError, "strategy"):
            summarize_train_probes([dict(row, arm="prototype")])


if __name__ == "__main__":
    unittest.main()
