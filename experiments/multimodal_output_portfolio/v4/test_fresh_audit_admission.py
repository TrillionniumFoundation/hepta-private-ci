"""Nominal fresh-audit inputs; not a sandbox for hostile Python code."""
from collections import namedtuple
from fractions import Fraction
import unittest

from counterfactual_audit import evaluate, evaluate_dependence
from joint_evidence_generation import EMIT, JointState, full_outcome_audit
from portfolio import Allocation, Config, State, STOP


class FreshAuditAdmissionTests(unittest.TestCase):
    def test_counterfactual_audits_reject_structural_roots(self):
        structural = namedtuple("Structural", "levels remaining step active_mask")
        cfg = Config(activation_cost=5, risk_aversion=0)
        def policy(state):
            return Allocation((1, 0, 0, 0)) if state.step == 0 else STOP

        for initial in (structural((0, 0, 0, 0), 12, 0, 0),
                        structural((0, 0, 0, 0), 12, 0, 1), None):
            with self.subTest(initial=initial):
                with self.assertRaisesRegex(ValueError, "four-modal emission"):
                    evaluate(initial, cfg, policy)
                with self.assertRaisesRegex(ValueError, "four-modal emission"):
                    evaluate_dependence(initial, cfg, policy,
                                        (((0, 0, 0, 0), 1.0),))

    def test_joint_audit_rejects_structural_outer_state(self):
        structural = namedtuple("StructuralJoint", "generation p_zero witness_seen")
        for initial in (structural(State((0, 0, 0, 0), 12), Fraction(1, 2), False),
                        None):
            with self.subTest(initial=initial):
                with self.assertRaisesRegex(ValueError, "first decision boundary"):
                    full_outcome_audit(initial, Config(), lambda _s: EMIT)

    def test_ordinary_subclasses_preserve_full_episode_cost(self):
        class PublicState(State):
            pass

        class PublicJointState(JointState):
            pass

        cfg = Config(activation_cost=5, risk_aversion=0)
        initial = PublicState((0, 0, 0, 0), 12)
        action = Allocation((1, 0, 0, 0))

        def policy(state):
            return action if state.step == 0 else STOP

        self.assertEqual(evaluate(initial, cfg, policy)["mean_paid_units"], 10)
        self.assertEqual(evaluate_dependence(
            initial, cfg, policy, (((0, 0, 0, 0), 1.0),))["mean_paid_units"], 10)
        joint = PublicJointState(initial, Fraction(1, 2))
        report = full_outcome_audit(
            joint, cfg, lambda s: action if s.generation.step == 0 else EMIT)
        self.assertEqual(report["mean_modeled_cost"], 10)


if __name__ == "__main__":
    unittest.main()
