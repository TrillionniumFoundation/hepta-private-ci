"""Behavioral checks for the shared-content and unbounded endpoint controls."""

from pathlib import Path
import unittest

import numpy as np
import torch

from ..round7.model import load_model
from ..round7.policy import run_episode
from ..round7.task import TaskParameters, generate_episode
from .control_exchange import exchanged_model
from .gaussian_policy import UnboundedGaussianPolicy
from .kernels import gaussian_propagate


class ControlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        source = Path(__file__).parents[1] / "round7/evidence/fits_primary/first_passage_none_11.json"
        cls.anchor = load_model(source)[0]

    def test_probit_gaussian_identical_decisions_and_continuous_state(self):
        model = exchanged_model(self.anchor, "continuous", "r8-brownian-images-v1")
        for deployment in ("hard", "mean"):
            for world in range(6):
                episode = generate_episode(91000 + world, TaskParameters())
                paths = [run_episode(UnboundedGaussianPolicy(model, seed=40 + world,
                          deployment=deployment, operator=operator), episode)
                         for operator in ("gaussian", "probit")]
                self.assertEqual(paths[0]["registered_return"], paths[1]["registered_return"])
                for left, right in zip(paths[0]["steps"], paths[1]["steps"], strict=True):
                    self.assertEqual(left["requested_action"], right["requested_action"])
                    self.assertEqual(left["prediction"]["q"], right["prediction"]["q"])
                    self.assertEqual(left["prediction"]["moments"], right["prediction"]["moments"])

    def test_unbounded_state_and_ou_semigroup(self):
        mean, variance = gaussian_propagate(0, 0, 4, 0.45, 2)
        self.assertEqual(float(mean), 8)
        self.assertAlmostEqual(float(variance), 2 * 0.45 ** 2)
        full = gaussian_propagate(0.2, 0.13, 0.8, 0.45, 2, leak=0.35)
        half = gaussian_propagate(0.2, 0.13, 0.8, 0.45, 1, leak=0.35)
        split = gaussian_propagate(*half, 0.8, 0.45, 1, leak=0.35)
        np.testing.assert_allclose([float(x) for x in full], [float(x) for x in split], atol=1e-14, rtol=0)


if __name__ == "__main__":
    unittest.main()
