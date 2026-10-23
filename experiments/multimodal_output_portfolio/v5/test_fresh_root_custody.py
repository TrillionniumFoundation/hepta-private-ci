"""Reject fake stage-zero activation and evidence purchases in finite v5.

The synthetic audit is not a real hardware cost attestation or evidence witness.
Its physical-*unit* conservation nevertheless assumes the first episode state
has not silently prepaid Cell activations or witness observations.
"""
import unittest
from fractions import Fraction

from joint_portfolio import (
    Profile, PublicState, Refine, STOP, cost, independent_path_audit,
    observe_refinement,
)


class FreshRootCustodyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Profile(horizon=2, activation_cost=5, gamma=0)

    def test_forged_root_activation_cannot_waive_switch_charge(self):
        fresh = PublicState((0, 0, 0, 0), Fraction(1, 2), 12)
        action = Refine((1, 0, 0, 0))
        self.assertEqual(cost(fresh, action, self.cfg), 6)
        # Before this admission fence, a stage-zero active_mask=1 was
        # permitted and reduced the same action cost from 6 to 1.
        for mask in (1, 5, 15):
            with self.subTest(mask=mask):
                with self.assertRaisesRegex(ValueError, "invalid public state"):
                    PublicState((0, 0, 0, 0), Fraction(1, 2), 12,
                                stage=0, active_mask=mask)

    def test_forged_root_witness_cannot_skip_information_provenance(self):
        # witnessed=True would claim a paid observation before any
        # recorded QUERY, disabling the only legitimate query action.
        with self.assertRaisesRegex(ValueError, "invalid public state"):
            PublicState((2, 2, 2, 2), Fraction(1, 2), 12,
                        stage=0, active_mask=0, witnessed=True)

    def test_legitimate_continuation_keeps_paid_activation_mask(self):
        initial = PublicState((0, 0, 0, 0), Fraction(1, 2), 12)
        action = Refine((1, 0, 0, 0))
        child = observe_refinement(initial, action, 2, self.cfg)
        self.assertEqual(child.stage, 1)
        self.assertEqual(child.active_mask, 1)
        self.assertFalse(child.witnessed)
        self.assertEqual(child.remaining, 6)
        self.assertEqual(cost(child, action, self.cfg), 1)

    def test_legitimate_fresh_root_still_replays_full_path(self):
        initial = PublicState((2, 2, 2, 2), Fraction(1, 2), 4)
        report = independent_path_audit(initial, self.cfg, lambda _: STOP)
        self.assertTrue(report["all_four_outputs"])
        self.assertTrue(report["all_funded"])
        self.assertEqual(report["support_paths"], 2)
        self.assertEqual(report["mean_paid_units"], 4)


if __name__ == "__main__":
    unittest.main()
