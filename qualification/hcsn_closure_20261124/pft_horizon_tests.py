"""Independent stationarity and causality checks for the synthetic control study."""

import unittest

import numpy as np

from . import pft_horizon as horizon
from . import pft_linear as pft


class HorizonTests(unittest.TestCase):
    def test_remaining_horizon_maps_match_exact_first_action(self):
        spec = dict(horizon.SPEC, horizon=3, reveal_transition=2)
        theta = np.array([0.2, -0.1, 0.3, 0.4])
        system, C, R = horizon.make_system(4, 17, theta, spec)
        ledger = dict(feature_response=0, solve=0, validation=0, communication=0)
        prepared = horizon.prepare(system, ledger)
        state = np.r_[theta, np.array([0.1, -0.3, 0.2, 0.7])]
        for k, mapping in enumerate(prepared["maps"]):
            expected = -np.linalg.solve(
                mapping["H"],
                mapping["G"].T @ (mapping["O"] @ state - mapping["target"]),
            )[:4]
            actual = horizon.choose("full_riccati", state, k, prepared, 32)
            np.testing.assert_allclose(expected, actual, atol=1e-12)
        run = pft.rollout(prepared["full"], state)
        measured = horizon.score(run, theta, C, R, system[-1][0], spec)
        self.assertAlmostEqual(run["objective"], measured["total"], places=13)

    def test_late_information_cannot_change_earlier_actions(self):
        spec = dict(horizon.SPEC, horizon=3, reveal_transition=2)
        theta = np.zeros(4)
        system, _, _ = horizon.make_system(4, 17, theta, spec)
        ledger = dict(feature_response=0, solve=0, validation=0, communication=0)
        prepared = horizon.prepare(system, ledger)
        noise = np.zeros((3, 8))
        changed = noise.copy()
        changed[1, 4:] = np.array([1.0, -1.0, 0.5, -0.7])
        for method in horizon.METHODS:
            a = horizon.simulate(method, np.zeros(8), noise, prepared, spec, ledger)
            b = horizon.simulate(method, np.zeros(8), changed, prepared, spec, ledger)
            np.testing.assert_array_equal(a["actions"][:2], b["actions"][:2])
        full = horizon.simulate(
            "full_riccati", np.zeros(8), changed, prepared, spec, ledger
        )
        self.assertGreater(np.linalg.norm(full["actions"][2]), 0.01)


if __name__ == "__main__":
    unittest.main()
