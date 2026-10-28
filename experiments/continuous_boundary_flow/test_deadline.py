"""Regression coverage for public deadline equality under horizon shift."""

from dataclasses import replace
import unittest

import numpy as np

from .common import ARMS, CANDIDATES
from .math_model import TaskSpec, build_model, solve_dp
from .models import ActorAdapter, boundary_features


class DeadlineInformation(unittest.TestCase):
    def test_every_arm_reconstructs_the_same_absolute_remaining_deadline(self):
        for horizon in (8, 16):
            spec = replace(TaskSpec(), horizon=horizon, dt=0.65)
            model = build_model(spec, n_grid=32)
            dp = solve_dp(model)
            public = []
            for arm in ARMS:
                actor = ActorAdapter(
                    spec,
                    dp,
                    arm,
                    CANDIDATES[1],
                    9003,
                    boundary_weights=np.zeros(20) if arm == "learned_margin" else None,
                )
                raw = actor.step(
                    np.array([8]), horizon, np.array([0.0]), np.array([0.0])
                )["raw"][0]
                self.assertAlmostEqual(raw[1] * 16 * raw[10], horizon * spec.dt)
                public.append(raw[:11])
            np.testing.assert_allclose(
                public, np.broadcast_to(public[0], (len(ARMS), 11))
            )
        self.assertNotEqual(8 / 16.0, 16 / 16.0)

    def test_same_remaining_task_has_no_initial_horizon_normalization_leak(self):
        a = replace(TaskSpec(), horizon=8)
        b = replace(TaskSpec(), horizon=16)
        np.testing.assert_array_equal(boundary_features(a, 6), boundary_features(b, 6))
        for spec in (a, b):
            model = build_model(spec, n_grid=32)
            actor = ActorAdapter(
                spec, solve_dp(model), "fixed_margin", CANDIDATES[1], 9003
            )
            raw = actor.step(np.array([8]), 6, np.array([0.0]), np.array([0.0]))["raw"][
                0
            ]
            self.assertEqual(raw[1], 6 / 16.0)


if __name__ == "__main__":
    unittest.main()
