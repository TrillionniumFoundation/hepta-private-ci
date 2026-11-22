"""Independent constant-law, coupled-block, subdivision and derivative fixtures."""

import math
import unittest

import numpy as np
import torch

from .clock_model import (
    WRITE_RATE,
    continuous_content_transition,
    execute_sequence,
    make_clock_model,
)


class ClockModelTests(unittest.TestCase):
    def test_constant_active_cell_matches_scalar_analytic_law(self):
        density = torch.tensor([[[1.0], [0.2]]], dtype=torch.float64)
        mark = density.new_tensor([[0.7]])
        dt = 0.3
        transition = density.new_ones(1, 1, 1)
        killed = torch.exp(-WRITE_RATE * density.new_tensor([[[dt]]]))
        zero = density.new_zeros(1, 1, 1)
        result, counts = continuous_content_transition(
            density, mark, transition, killed, zero, zero
        )
        expected = 0.7 + (0.2 - 0.7) * math.exp(-WRITE_RATE * dt)
        self.assertAlmostEqual(float(result[0, 1, 0]), expected, places=14)
        self.assertEqual(float(counts.abs().sum()), 0.0)

    def test_reduced_solution_matches_independent_coupled_block_exponential(self):
        g = torch.tensor([[-2.0, 2.0], [3.0, -3.0]], dtype=torch.float64)
        d = torch.diag(g.new_tensor([1.0, 0.0]))
        mark, duration, rate = 0.4, 0.23, 1.7
        initial = g.new_tensor([0.7, 0.3, 0.1, -0.05])
        block = g.new_zeros(4, 4)
        block[:2, :2], block[:2, 2:], block[2:, 2:] = g, rate * mark * d, g - rate * d
        expected = initial @ torch.matrix_exp(block * duration)
        density = initial.reshape(1, 2, 2)
        zero = g.new_zeros(1, 2, 1)
        actual, _ = continuous_content_transition(
            density,
            g.new_tensor([[mark]]),
            torch.matrix_exp(g * duration)[None],
            torch.matrix_exp((g - rate * d) * duration)[None],
            zero,
            zero,
        )
        torch.testing.assert_close(actual.reshape(-1), expected, atol=1e-13, rtol=1e-12)

    def test_subdivision_matches_masked_and_continuous_but_exposes_legacy(self):
        model = make_clock_model()
        coarse = {
            "x": np.array([[[0.4, -0.2, 0.1, 0.0]]], dtype=np.float64),
            "dt": np.array([[0.2]], dtype=np.float64),
            "write_mask": np.ones((1, 1)),
        }
        fine = {
            "x": np.repeat(coarse["x"], 4, axis=1),
            "dt": np.full((1, 4), 0.05),
            "write_mask": np.array([[1.0, 0.0, 0.0, 0.0]]),
        }
        differences = {}
        for law in ("event_mask", "continuous_write", "legacy_observation"):
            a, b = (
                execute_sequence(model, coarse, law),
                execute_sequence(model, fine, law),
            )
            differences[law] = float((a["density"] - b["density"]).abs().max())
            torch.testing.assert_close(
                a["density"][:, 0], b["density"][:, 0], rtol=1e-11, atol=1e-12
            )
            if law != "legacy_observation":
                torch.testing.assert_close(
                    a["density"], b["density"], rtol=1e-11, atol=1e-12
                )
                torch.testing.assert_close(
                    a["counts"], b["counts"], rtol=1e-11, atol=1e-12
                )
        self.assertGreater(differences["legacy_observation"], 1e-4)

    def test_continuous_kernel_gradient_matches_finite_difference(self):
        model = make_clock_model()
        data = {
            "x": np.array([[[0.2, -0.1, 0.4, 0.0]]], dtype=np.float64),
            "dt": np.array([[0.17]], dtype=np.float64),
            "write_mask": np.ones((1, 1)),
        }

        def loss():
            output = execute_sequence(model, data, "continuous_write")
            return output["density"][:, 1].square().sum() + output["counts"][:, 1].sum()

        gradient = torch.autograd.grad(loss(), model.encoder.writer.bias)[0][0]
        h = 1e-5
        with torch.no_grad():
            original = model.encoder.writer.bias[0].item()
            model.encoder.writer.bias[0] = original + h
            plus = float(loss())
            model.encoder.writer.bias[0] = original - h
            minus = float(loss())
            model.encoder.writer.bias[0] = original
        self.assertAlmostEqual(float(gradient), (plus - minus) / (2 * h), delta=2e-8)


if __name__ == "__main__":
    unittest.main()
