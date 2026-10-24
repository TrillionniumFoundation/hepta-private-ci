"""Fail closed when exact positive Bayesian/path mass vanishes in float replay."""
from fractions import Fraction
import unittest

from portfolio import Allocation, Config, State
from joint_evidence_generation import (
    EMIT, JointState, full_outcome_audit,
)


class ExactFractionSupportTests(unittest.TestCase):
    def test_unrepresentable_positive_truth_class_is_not_declared_impossible(self):
        tiny = Fraction(1, 10**500)
        for prior in (tiny, 1 - tiny):
            with self.subTest(rare_truth_is_zero=prior == tiny):
                with self.assertRaisesRegex(
                    ValueError, "unsupported public belief-state"
                ):
                    JointState(State((0, 0, 0, 0), 30), prior)

    def test_supported_truth_shock_path_must_not_disappear(self):
        # The original truth mass is representable, but 1e-322*(1/5)^3
        # underflows to binary zero. The exact Fraction law still sums to 1.
        initial = JointState(State((0, 0, 0, 0), 30),
                             Fraction(1, 10**322))
        cfg = Config(horizon=3)

        def choose(s):
            return (Allocation((1, 0, 0, 0))
                    if s.generation.step < cfg.horizon else EMIT)

        with self.assertRaisesRegex(
            ValueError, "positive exact audit path mass underflow"
        ):
            full_outcome_audit(initial, cfg, choose)

    def test_representable_small_fraction_retains_all_paths(self):
        # Same trajectory, but every exactly positive branch remains float-positive.
        initial = JointState(State((0, 0, 0, 0), 30),
                             Fraction(1, 10**300))
        cfg = Config(horizon=3)

        def choose(s):
            return (Allocation((1, 0, 0, 0))
                    if s.generation.step < cfg.horizon else EMIT)

        result = full_outcome_audit(initial, cfg, choose)
        self.assertEqual(result["outcomes"], 54)
        self.assertTrue(result["four_outputs_emitted"])
        self.assertEqual(result["budget_violations"], 0)


if __name__ == "__main__":
    unittest.main()
