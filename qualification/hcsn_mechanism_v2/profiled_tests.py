"""Envelope derivatives against independent finite differences after re-solving."""

import unittest

import numpy as np
import torch

from .profiled import backward_step, forward_loss, parameter_mode, prepare


class ProfiledTests(unittest.TestCase):
    def test_profile_derivative_rebuilds_operator_and_resolves_head(self):
        # Fixed, explicitly constructed toy data; no registered train/final split.
        x = np.zeros((4, 4, 4), dtype=np.float64)
        x[:, :, 0] = np.array([0.1, 0.3, 0.5, 0.8])[:, None]
        x[:, :, 1] = np.array([-0.2, 0.1, 0.2, -0.1])[:, None]
        data = {
            "x": x,
            "dt": np.full((4, 4), 0.08),
            "y": np.array([[0.8], [0.6], [0.2], [0.1]]),
        }
        model, _, _ = prepare("first_passage", data, 0.05, 0.03)
        parameter_mode(model, "profile_bp")
        _, _, _ = backward_step(model, data, 0.03, True)
        parameter = model.flow.encoder.drive.weight
        analytic = float(parameter.grad[0, 1])
        original = float(parameter[0, 1])
        values = []
        epsilon = 1e-5
        for sign in (1, -1):
            with torch.no_grad():
                parameter[0, 1] = original + sign * epsilon
                value, _ = forward_loss(model, data, 0.03, True)
                values.append(float(value))
        with torch.no_grad():
            parameter[0, 1] = original
        numeric = (values[0] - values[1]) / (2 * epsilon)
        self.assertAlmostEqual(analytic, numeric, delta=2e-7)
        self.assertGreater(abs(analytic), 1e-8)

    def test_same_initial_objective_and_eligible_union(self):
        x = np.zeros((4, 4, 4), dtype=np.float64)
        x[:, 0, 0] = np.array([-0.5, -0.2, 0.2, 0.5])
        data = {
            "x": x,
            "dt": np.full((4, 4), 0.1),
            "y": np.array([[-0.3], [-0.1], [0.2], [0.4]]),
        }
        model, _, _ = prepare("association", data, 0.05, 0.001)
        ordinary, _ = forward_loss(model, data, 0.001, False)
        profiled, _ = forward_loss(model, data, 0.001, True)
        torch.testing.assert_close(ordinary, profiled, atol=1e-13, rtol=0)
        joint = set(parameter_mode(model, "joint_bp"))
        outer = set(parameter_mode(model, "profile_bp"))
        self.assertEqual(joint - outer, {"readout.weight", "readout.bias"})
        self.assertEqual(
            sum(p.numel() for p in model.parameters() if p.requires_grad), 30
        )


if __name__ == "__main__":
    unittest.main()
