import unittest

import numpy as np

from experiments.first_passage_operator.free_boundary import NaturalSpikeSpec
from experiments.first_passage_deadline.expiry import continuum_first_layer, lattice_first_layer


class ExpiryOracleTests(unittest.TestCase):
    def test_continuum_resolvent_has_matching_and_obstacle_inequalities(self):
        spec = NaturalSpikeSpec(0., .45, 0., .2, .2, .6)
        dt = .005
        initial = continuum_first_layer(spec, dt, [spec.spike_cost])
        b = initial["boundary"]
        x = np.r_[np.linspace(.3, b - 1e-8, 60), b, b + .1]
        result = continuum_first_layer(spec, dt, x)
        g = np.maximum(x - spec.spike_cost, 0)
        gap = result["value"] - g
        equation = (1 + spec.discount * dt) * result["value"] - .5 * spec.sigma ** 2 * dt * result["second"] - g
        self.assertLess(np.max(np.abs(np.minimum(equation, gap))), 1e-12)
        self.assertGreaterEqual(gap.min(), -1e-14)
        self.assertGreaterEqual(equation.min(), -1e-14)
        self.assertAlmostEqual(result["value"][-2], b - spec.spike_cost, delta=1e-14)
        self.assertAlmostEqual(result["first"][-3], 1.0, delta=1e-7)

    def test_geometric_lattice_oracle_satisfies_complementarity(self):
        spec = NaturalSpikeSpec(0., .45, 0., .2, .2, .6)
        states = spec.spike_cost + np.arange(-200, 101) * .01
        result = lattice_first_layer(spec, .005, .01, states)
        self.assertLess(result["complementarity_residual"], 1e-12)
        self.assertGreaterEqual(result["first_stop_score"], 0)
        self.assertLess(result["previous_continue_score"], 0)
        self.assertTrue(result["finite_lower_cannot_change_boundary"])


if __name__ == "__main__":
    unittest.main()
