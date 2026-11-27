"""Independent positive density integration checks for continuation formulas."""

import unittest

import mpmath as mp
import numpy as np

from qualification.hcsn_initial_law.migration import MigrationBasis
from .cost_audit import PROFILES, generator
from .cost_reference import values
from .migration1024 import MigrationBasis1024


class TestCostReference(unittest.TestCase):
    def test_fixed_near_profiles_use_their_distinct_preregistered_endpoints(self):
        parameters = {"mu": -0.11999999999999998, "sigma": 0.35}
        near800 = generator(PROFILES[1], parameters)
        near960 = generator(PROFILES[2], parameters)
        self.assertEqual(near800.nodes[800], 0.5)
        self.assertEqual(near960.nodes[960], 0.48)
        self.assertEqual(len(near800.nodes), 1025)
        self.assertEqual(len(near960.nodes), 1025)

    def test_original_uniform_and_tail_values_against_positive_integrals(self):
        parameters = {"mu": -0.12, "sigma": 0.35, "discount": 0.15}
        grid = {"endpoint": 4.8, "active_cells": 16, "tail_rate": 1.0,
                "refractory": 0.2, "phase_cells": 8}
        actual = values(parameters, 0.32, 0.2, grid, tuple(np.linspace(0, 8, 33)))
        with mp.workdps(70):
            mu, sigma, q, reset, delay = map(mp.mpf, ("-.12", ".35", ".15", ".32", ".2"))
            alpha = (mu + mp.sqrt(mu**2 + 2 * q * sigma**2)) / sigma**2
            beta = mp.sqrt(mu**2 + 2 * q * sigma**2) / sigma**2
            baseline, reward = mp.mpf(".4") / q, mp.mpf(1)
            phi = lambda x: mp.exp(-alpha * x)
            finite_phi = lambda x: mp.exp(-mu * x / sigma**2) * mp.sinh(beta * (8 - x)) / mp.sinh(beta * 8)

            def value_function(transform):
                r = transform(reset)
                vr = (baseline * (1 - r) + reward * r) / (1 - mp.exp(-q * delay) * r)
                return lambda x: baseline + transform(x) * (reward + mp.exp(-q * delay) * vr - baseline)

            for name, transform in (("halfline_original", phi), ("finite_original", finite_phi)):
                function = value_function(transform)
                for cell in (0, 3, 15):
                    lo, hi = mp.mpf(".3") * cell, mp.mpf(".3") * (cell + 1)
                    expected = mp.quad(function, [lo, hi]) / (hi - lo)
                    self.assertAlmostEqual(actual[name][cell], float(expected), places=13)
                if name == "halfline_original":
                    tail = mp.quad(lambda x: mp.exp(-(x - mp.mpf("4.8"))) * function(x), [mp.mpf("4.8"), 8, mp.inf])
                else:
                    tail = mp.quad(lambda x: mp.exp(-(x - mp.mpf("4.8"))) * function(x), [mp.mpf("4.8"), 8]) + baseline * mp.exp(-mp.mpf("3.2"))
                self.assertAlmostEqual(actual[name][16], float(tail), places=13)

    def test_phase_value_is_uniform_remaining_time_not_an_extra_hit_reward(self):
        parameters = {"mu": -0.12, "sigma": 0.35, "discount": 0.15}
        grid = {"endpoint": 4.8, "active_cells": 16, "tail_rate": 1.0,
                "refractory": 0.2, "phase_cells": 8}
        actual = values(parameters, 0.32, 0.2, grid, tuple(np.linspace(0, 8, 33)))
        for key in ("halfline_original", "finite_original"):
            self.assertTrue(np.all(np.diff(actual[key][17:]) < 0))
            ratios = actual[key][18:] / actual[key][17:-1]
            self.assertLess(float(np.max(abs(ratios - np.exp(-0.15 * 0.025)))), 5e-15)

    def test_independent_cap_extension_does_not_mutate_frozen_cap(self):
        args = (4.8, 16, 1.0, 0.2, 8, 8.0, 1024)
        with self.assertRaises(ValueError):
            MigrationBasis(*args)
        candidate = MigrationBasis1024(*args)
        self.assertEqual(len(candidate.actual_nodes), 1025)
        self.assertEqual(candidate.actual_nodes[0], 0)
        self.assertEqual(candidate.actual_nodes[-1], 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
