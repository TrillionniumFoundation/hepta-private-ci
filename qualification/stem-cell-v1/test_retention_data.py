"""Joint qualification cannot be satisfied by preserving an unlearning Reader."""
from dataclasses import replace
import unittest

from binding_protocol import build_binding_protocol, score_binding_probabilities, verify_binding_cases
from retention_data import build_augmentation, joint_gate, natural_baselines, natural_metrics


class RetentionDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = build_binding_protocol(seed=41)
        cls.augmentation, cls.report = build_augmentation(cls.parts)

    def fixtures(self):
        old = self.parts["reader_train"]
        internal = self.parts["internal_tune"]
        perfect = lambda cases: [.99 if c.label else .01 for c in cases]
        baseline = score_binding_probabilities(old, perfect(old))
        relation = score_binding_probabilities(internal, perfect(internal))
        constants = natural_baselines(old)
        start = natural_metrics(old, [1.] * len(old))
        learned = natural_metrics(old, perfect(old))
        return baseline, relation, constants, start, learned

    def test_augmentation_reconstructs_truth_and_disjoint_membership(self):
        cases, report = build_augmentation(self.parts)
        self.assertEqual((cases, report), (self.augmentation, self.report))
        self.assertEqual(verify_binding_cases(cases)["groups"], 256)
        self.assertFalse({c.source_hash for c in cases} &
                         {c.source_hash for v in self.parts.values() for c in v})
        broken = (replace(cases[0], label=1-cases[0].label), *cases[1:])
        with self.assertRaises(ValueError):
            verify_binding_cases(broken)

    def test_actual_learning_can_pass_all_joint_conditions(self):
        old, relation, constants, start, learned = self.fixtures()
        self.assertTrue(joint_gate(old, old, relation, learned, start, constants)["passed"])

    def test_freezing_old_task_and_constant_new_predictions_fails(self):
        old, relation, constants, start, _ = self.fixtures()
        gate = joint_gate(old, old, relation, start, start, constants)
        self.assertFalse(gate["passed"])
        self.assertIn("natural_F1a_gain_below_0.05", gate["reasons"])
        self.assertIn("natural_CE_not_5percent_below_prior", gate["reasons"])

    def test_learning_natural_without_relation_transfer_fails(self):
        old, _, constants, start, learned = self.fixtures()
        bad = score_binding_probabilities(self.parts["internal_tune"], [.5] * 64)
        gate = joint_gate(old, old, bad, learned, start, constants)
        self.assertFalse(gate["passed"])
        self.assertIn("relation_pairs_below_0.50", gate["reasons"])

    def test_saved_half_probability_is_strictly_negative(self):
        cases = self.parts["reader_train"]
        self.assertEqual(natural_metrics(cases, [.5] * len(cases))["f1_a"], 0.)
        with self.assertRaises(ValueError):
            natural_metrics(cases, [float("nan")] * len(cases))

    def test_nonfinite_or_incomplete_joint_panels_are_rejected(self):
        old, relation, constants, start, learned = self.fixtures()
        for bad in ({**learned, "probability_CE": float("nan")},
                    {**learned, "candidates": learned["candidates"] - 1}):
            with self.assertRaises(ValueError):
                joint_gate(old, old, relation, bad, start, constants)


if __name__ == "__main__":
    unittest.main()
