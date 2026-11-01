"""Behavior checks for count interventions and fitted recurrence interfaces."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "recovered/v3"))

import numpy as np
import torch
from experiments.hcsn_mechanism_content_v2.renewal import Physics, content_from_counts
from .count_interventions import IntervenedRenewal, transform_counts
from .recurrent_counts import RecurrentCountModel, FittedRecurrentCore


class MechanismTests(unittest.TestCase):
    def test_mean_preserving_intervention_keeps_reachable_mean(self):
        physics = Physics(-.8, .55, .45, .18)
        original = IntervenedRenewal().counts(.15, 2.4, physics)
        altered = transform_counts(original, "mean_two_point")
        self.assertGreater(original[2:].sum(), .3)
        self.assertAlmostEqual(float(original @ np.arange(32)), float(altered @ np.arange(32)), places=12)
        self.assertAlmostEqual(float(altered.sum()), 1, places=12)
        self.assertLessEqual(np.count_nonzero(altered), 2)
        transition = np.roll(np.eye(5), 1, axis=0)
        self.assertGreater(float(np.abs(content_from_counts(original, np.eye(5)[0], transition)
                                      - content_from_counts(altered, np.eye(5)[0], transition)).sum()), .01)

    def test_multiple_transition_intervention_changes_count_not_zero_mass(self):
        original = IntervenedRenewal().counts(.15, 2.4, Physics(-.8, .55, .45, .18))
        altered = transform_counts(original, "single_transition")
        self.assertEqual(altered[0], original[0])
        self.assertEqual(float(altered[2:].sum()), 0)
        self.assertGreater(float(original @ np.arange(32)), float(altered @ np.arange(32)))

    def test_refractory_remaining_blocks_all_count_paths(self):
        physics = Physics(-.8, .55, .45, .18)
        expected = np.zeros(32)
        expected[0] = 1
        for mode in ("original", "mean_two_point", "single_transition"):
            np.testing.assert_array_equal(IntervenedRenewal(mode).counts(.45, .1, physics, .15), expected)

    def test_learned_outputs_have_support_and_finite_gradients(self):
        torch.manual_seed(918)
        packet = torch.tensor([[.4, .3, -.7, .4, .5, .2, .0],
                               [.5, .2, -.4, .3, .5, .2, .19]], dtype=torch.float64)
        for family in ("gru", "ssm"):
            model = RecurrentCountModel(family, np.zeros(7), np.ones(7))
            probs = model(packet).softmax(-1)
            self.assertTrue(torch.isfinite(probs).all())
            self.assertTrue(torch.allclose(probs.sum(-1), torch.ones(2, dtype=torch.float64)))
            self.assertEqual(float(probs[1, 2:].sum()), 0)
            (-probs[:, 0].log().sum()).backward()
            self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters()))
            core = FittedRecurrentCore(model)
            np.testing.assert_array_equal(core.counts(.5, .1, Physics(-.4, .3, .5, .2), .15),
                                          np.r_[1., np.zeros(31)])

    def test_bad_laws_are_rejected(self):
        for p in ([.2, .2], [-.2, 1.2], [float("nan"), 1], [1]):
            with self.assertRaises(ValueError):
                transform_counts(p, "mean_two_point")


if __name__ == "__main__":
    unittest.main()
