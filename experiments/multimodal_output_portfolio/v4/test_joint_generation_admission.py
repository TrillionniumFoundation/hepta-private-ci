"""Finite Python API admission; not hostile-code isolation or real metering."""
from collections import namedtuple
from fractions import Fraction
import unittest

from portfolio import Allocation, Config, State, advance, charge
from joint_evidence_generation import EMIT, JointState, full_outcome_audit


class PublicState(State):
    """Ordinary nominal subclass: all inherited admission checks remain active."""


class JointGenerationAdmissionTests(unittest.TestCase):
    def test_structural_generation_cannot_bypass_root_activation_guard(self):
        generation_type = namedtuple(
            "StructuralGeneration", "levels remaining step active_mask"
        )
        # An immutable lookalike is still not an admitted State. In particular,
        # mask=1 formerly waived five modeled units at the first decision.
        for mask in (0, 1):
            generation = generation_type((0, 0, 0, 0), 12, 0, mask)
            with self.subTest(mask=mask):
                with self.assertRaisesRegex(ValueError, "unsupported public belief-state"):
                    JointState(generation, Fraction(1, 2))

    def test_non_state_generation_rejects_before_field_access(self):
        for generation in (None, object(), {}, "State", True):
            with self.subTest(generation_type=type(generation).__name__):
                with self.assertRaisesRegex(ValueError, "unsupported public belief-state"):
                    JointState(generation, Fraction(1, 2))

    def test_ordinary_state_subclass_keeps_paid_transition_and_audit(self):
        cfg = Config(activation_cost=5, risk_aversion=0)
        generation = PublicState((0, 0, 0, 0), 12)
        root = JointState(generation, Fraction(1, 2))
        action = Allocation((1, 0, 0, 0))
        self.assertIs(root.generation, generation)
        self.assertEqual(charge(generation, action, cfg), 6)
        successor = advance(generation, action, 2, cfg)
        self.assertEqual(
            (successor.step, successor.remaining, successor.active_mask),
            (1, 6, 1),
        )
        self.assertEqual(JointState(successor, root.p_zero).generation, successor)
        report = full_outcome_audit(
            root, cfg, lambda s: action if s.generation.step == 0 else EMIT
        )
        self.assertEqual(report["mean_modeled_cost"], 10)
        self.assertEqual(report["budget_violations"], 0)
        self.assertTrue(report["four_outputs_emitted"])
        with self.assertRaisesRegex(ValueError, "invalid public portfolio state"):
            PublicState((0, 0, 0, 0), 12, active_mask=1)

    def test_nonregistered_priors_remain_explicit_model_parameters(self):
        # A generic hypothetical prior is not an authenticated source claim.
        # Do not narrow the existing distribution parameter to easy/hard modes.
        cfg = Config(risk_aversion=0)
        for prior in (Fraction(0), Fraction(1, 3), Fraction(1)):
            with self.subTest(prior=prior):
                root = JointState(State((2, 2, 2, 2), 4), prior)
                self.assertEqual(root.p_zero, prior)
                report = full_outcome_audit(root, cfg, lambda _s: EMIT)
                self.assertAlmostEqual(
                    report["mean_external_loss"], float(4 * min(prior, 1 - prior))
                )
                self.assertEqual(report["mean_modeled_cost"], 4)
                self.assertEqual(report["query_probability"], 0)


if __name__ == "__main__":
    unittest.main()
