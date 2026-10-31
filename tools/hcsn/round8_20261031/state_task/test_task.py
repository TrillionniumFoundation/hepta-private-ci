"""Independent kernel parity and Bayesian history sufficiency checks."""

import json
import unittest

import numpy as np

from .data import HERE, MODES, PRIOR, make_data, teacher_components
from ..event_dynamics.event_kernel import first_hit


class TaskTests(unittest.TestCase):
    def test_teacher_matches_stable_kernel(self):
        protocol = json.loads((HERE / "protocol.json").read_text())
        for name in ("train", "low_noise", "moving_boundary"):
            data = make_data(name, protocol)
            query = data["query"][:64]
            expected = teacher_components(query)
            actual = np.array([[first_hit(d, mu, sigma, t, boundary_slope=slope)["probability"]
                for mu in MODES] for d, sigma, t, slope, _ in query])
            np.testing.assert_allclose(actual, expected, atol=2e-12, rtol=2e-10)

    def test_two_statistics_match_sequential_likelihood(self):
        protocol = json.loads((HERE / "protocol.json").read_text())
        data = make_data("train", protocol)
        for index in range(24):
            weights = PRIOR.copy()
            for dy, dt, sigma in data["history"][index, :data["lengths"][index]]:
                log_likelihood = -(dy - MODES * dt)**2 / (2 * sigma**2 * dt)
                weights *= np.exp(log_likelihood - log_likelihood.max())
                weights /= weights.sum()
            np.testing.assert_allclose(weights, data["posterior"][index], atol=2e-14)

    def test_query_cost_does_not_change_event_target(self):
        protocol = json.loads((HERE / "protocol.json").read_text())
        data = make_data("train", protocol)
        q = data["query"][:32].copy()
        reference = teacher_components(q)
        q[:, 4] = .99
        np.testing.assert_array_equal(reference, teacher_components(q))


if __name__ == "__main__":
    unittest.main()
