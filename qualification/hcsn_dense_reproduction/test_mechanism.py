"""Mechanism checks for the new identity, separate from science admission."""

import math
import unittest
import numpy as np
from .positive_phase import phase_count
from .profile import NearDenseGenerator, ControlledModel
from qualification.hcsn_graded.model import GradedJointModel


class Mechanism(unittest.TestCase):
    def test_exponential_waiting_time_integral(self):
        for t in (0.001, 0.02, 0.04, 0.16):
            lo = max(0.0, t - 0.025)
            expected = ((t - lo) - (math.exp(-2 * lo) - math.exp(-2 * t)) / 2) / 0.025
            result = phase_count([2.0], [0.0], [1.0], t)
            self.assertLess(abs(result["M"] - expected), 1e-14)

    def test_probability_and_domain_guards(self):
        for reset in ([0.5], [-1.0], [float("nan")]):
            with self.assertRaises(ValueError):
                phase_count([2.0], [0.0], reset, 0.02)
        with self.assertRaises(ValueError):
            phase_count([2.0], [0.0], [1.0], 0.21)

    def test_both_profiles_match_local_moments(self):
        for near, edge in ((800, 0.5), (960, 0.48)):
            s = NearDenseGenerator(1024, 8.0, -0.12, 0.35, 6.0, near, edge)
            a, b = np.diff(s.nodes)[:-1], np.diff(s.nodes)[1:]
            down, up = s.rates
            np.testing.assert_allclose(-down * a + up * b, -0.12, atol=1e-12)
            np.testing.assert_allclose(down * a**2 + up * b**2, 0.35**2, atol=1e-14)

    def test_reset_uses_actual_nodes(self):
        s = NearDenseGenerator(1024, 8.0, -0.12, 0.35, 6.0, 960, 0.48)
        m = ControlledModel(s, 0.32725, 0.2, 0.15)
        r = m.ingredients()[-1]
        self.assertAlmostEqual(float(r.sum()), 1.0)
        self.assertAlmostEqual(float(r @ s.nodes[1:-1]), 0.32725)

    def test_tighter_guard_is_private(self):
        s = NearDenseGenerator(32, 2.0, -0.12, 0.35, 6.0, 24, 0.5)
        kwargs = dict(query_times=[0.0], active=np.zeros(33), content=np.zeros((33, 1)), atol=1e-18)
        with self.assertRaises(ValueError):
            GradedJointModel(s, 0.32, 0.2, 0.15).solve(**kwargs)
        result = ControlledModel(s, 0.32, 0.2, 0.15).solve(**kwargs)
        self.assertEqual(result["internal_steps"], 0)


if __name__ == "__main__":
    unittest.main()
