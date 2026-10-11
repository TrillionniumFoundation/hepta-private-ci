"""Weak training objective probes do not evaluate held-out task quality."""

import math
import unittest

from stem_cell_training_probe import train_probe, summarize_train_probes


class TrainingProbeTests(unittest.TestCase):
    def test_correct_source_logit_gain_reduces_training_loss(self):
        probe = train_probe([0.0, 2.0, 0.0], [5.0, 2.0, 0.0], (0,))
        self.assertLess(probe["loss_delta"], 0)
        self.assertTrue(probe["weak_label_loss_improved"])
        self.assertLess(probe["native_margin"], 0)
        self.assertGreater(probe["learned_margin"], 0)
        self.assertTrue(probe["weak_source_support_not_entailment"])
        self.assertFalse(probe["usable_as_independent_generalization_evidence"])

    def test_unchanged_logits_show_no_fake_training_gain(self):
        probe = train_probe([2.0, 1.0, 0.0], [2.0, 1.0, 0.0], (0,))
        self.assertEqual(probe["loss_delta"], 0.0)
        self.assertFalse(probe["weak_label_loss_improved"])

    def test_multiple_supports_are_multi_positive_not_collapsed(self):
        single = train_probe([1.0, 4.0, -1.0, 0.0],
                             [1.0, 4.0, -1.0, 0.0], (0,))
        many = train_probe([1.0, 4.0, -1.0, 0.0],
                           [1.0, 4.0, -1.0, 0.0], (0, 1))
        self.assertLess(many["frozen_weak_label_loss"], single["frozen_weak_label_loss"])
        self.assertEqual(many["supported_candidate_count"], 2)

    def test_annotated_unanswerable_does_not_create_fake_evidence_positive(self):
        original = train_probe([2.0, 1.0, 0.0], [2.0, 1.0, 0.0], ())
        learned = train_probe([2.0, 1.0, 0.0], [2.0, 1.0, 4.0], ())
        self.assertTrue(original["annotated_unanswerable"])
        self.assertLess(learned["learned_weak_label_loss"],
                        original["frozen_weak_label_loss"])
        self.assertEqual(original["supported_candidate_count"], 0)

    def test_no_candidate_still_has_only_null_class(self):
        probe = train_probe([0.0], [0.0], ())
        self.assertEqual(probe["candidate_count"], 0)
        self.assertEqual(probe["frozen_weak_label_loss"], 0.0)
        self.assertIsNone(probe["native_margin"])

    def test_invalid_heldout_or_nonfinite_logits_cannot_sneak_in(self):
        for original, learned, pos in (
            ([1.0, 0.0], [1.0, 0.0], (1,)),
            ([1.0, 0.0], [1.0, 0.0], (0, 0)),
            ([1.0, 0.0], [1.0], (0,)),
            ([1.0, math.nan], [1.0, 0.0], (0,)),
            ([1.0, 0.0], [1.0, math.inf], (0,)),
        ):
            with self.subTest(pos=pos), self.assertRaises(ValueError):
                train_probe(original, learned, pos)

    def test_complete_failure_census_preserves_all_attempted_probes(self):
        good = train_probe([1.0, 0.0], [2.0, 0.0], (0,))
        records = [
            dict(stage=16, arm="gated", cell="general", status="succeeded",
                 probe=good),
            dict(stage=16, arm="gated", cell="general", status="failed"),
        ]
        summary = summarize_train_probes(records)["16/gated/general"]
        self.assertEqual(summary["attempted"], 2)
        self.assertEqual(summary["probe_failed"], 1)
        self.assertEqual(summary["improved_weak_training_examples"], 1)
        self.assertFalse(summary["generalization_claim"])


if __name__ == "__main__":
    unittest.main()
