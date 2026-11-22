"""Algebraic fixtures only; no formal namespace, task labels or model execution."""

import unittest

import numpy as np
import torch

from .representation import (
    feature_banks,
    fit_scaler,
    pool_sequence,
    predict,
    ridge_fit,
    spectrum_diagnostics,
    standardize,
)


class RepresentationTests(unittest.TestCase):
    def test_svd_solution_matches_independent_augmented_least_squares(self):
        x = torch.tensor(
            [
                [1.0, 2.0, 1.0],
                [2.0, 4.0, -1.0],
                [3.0, 6.0, 0.0],
                [4.0, 8.0, 1.0],
                [5.0, 10.0, -1.0],
            ],
            dtype=torch.float64,
        )
        y = x[:, 0].sin()
        state = ridge_fit(x, y, ridge=0.2)
        design = torch.cat((x, torch.ones(5, 1, dtype=x.dtype)), 1)
        penalty = torch.diag(x.new_tensor([0.2, 0.2, 0.2, 0.0]).sqrt())
        aug = torch.cat((design, penalty))
        target = torch.cat((y, y.new_zeros(4)))
        reference = torch.linalg.lstsq(aug, target).solution
        torch.testing.assert_close(
            state["weight"], reference[:-1], rtol=1e-10, atol=1e-11
        )
        torch.testing.assert_close(state["bias"], reference[-1], rtol=1e-10, atol=1e-11)
        self.assertEqual(state["diagnostics"]["rank"], 2)
        self.assertLess(state["diagnostics"]["normal_equation_residual_l2"], 1e-10)

    def test_train_scaler_stays_frozen_and_floor_limits_gain(self):
        x = torch.tensor([[0.0, 1.0], [1e-6, 1.0], [2e-6, 1.0]], dtype=torch.float64)
        empirical, floored = fit_scaler(x), fit_scaler(x, "bounded_floor", 0.05)
        future = x + x.new_tensor([0.1, 0.0])
        before = floored["mean"].clone()
        self.assertGreater(float(standardize(future, empirical)[:, 0].min()), 10000)
        self.assertLess(float(standardize(future, floored)[:, 0].max()), 2.001)
        torch.testing.assert_close(floored["mean"], before)

    def test_probability_projection_cannot_worsen_brier(self):
        x = torch.tensor([[-3.0], [0.2], [0.9], [5.0]], dtype=torch.float64)
        state = {"weight": [1.0], "bias": 0.0}
        target = x.new_tensor([0.0, 0.3, 0.8, 1.0])
        raw, clipped = predict(x, state), predict(x, state, "clip_unit")
        self.assertTrue(
            bool(((clipped - target).square() <= (raw - target).square()).all())
        )

    def test_added_feature_rank_distinguishes_duplicate_and_new_direction(self):
        x = torch.tensor(
            [[0.0, 0.0, 0.0], [1.0, 2.0, 1.0], [2.0, 4.0, 0.0], [3.0, 6.0, 1.0]],
            dtype=torch.float64,
        )
        duplicate = spectrum_diagnostics(x[:, :2], (1,))
        novel = spectrum_diagnostics(x, (2,))
        self.assertEqual(duplicate["extra_residual_rank"], 0)
        self.assertEqual(novel["extra_residual_rank"], 1)
        self.assertLess(duplicate["extra_residual_energy_fraction"], 1e-26)

    def test_exposure_pool_preserves_additive_rate_on_exact_refinement(self):
        names = (
            "event",
            "content_0",
            "content_1",
            "content_2",
            "content_3",
            "risk",
            "margin",
            "occupation",
            "call",
        )
        values = torch.ones(1, 2, 9, dtype=torch.float64)
        dt = values.new_tensor([[0.2, 0.4]])
        values[:, :, :5] = dt[:, :, None] * 2
        x = values.new_zeros(1, 2, 4)
        refined = values.repeat_interleave(2, 1)
        refined[:, :, :5] /= 2
        coarse, _ = pool_sequence(values, dt, x, names, "exposure")
        fine, _ = pool_sequence(
            refined,
            dt.repeat_interleave(2, 1) / 2,
            x.repeat_interleave(2, 1),
            names,
            "exposure",
        )
        torch.testing.assert_close(coarse[:, :5], fine[:, :5])
        torch.testing.assert_close(coarse[:, 9:14], fine[:, 9:14])
        # Unchanged interval first-hit probability is deliberately not a rate.
        self.assertNotEqual(float(coarse[0, 5]), float(fine[0, 5]))

    def test_chunking_preserves_bank_and_ignores_labels(self):
        class Stub:
            encoder = type(
                "FeatureNames",
                (),
                {
                    "feature_names": (
                        "event",
                        "content_0",
                        "content_1",
                        "content_2",
                        "content_3",
                        "risk",
                        "margin",
                        "occupation",
                        "call",
                    )
                },
            )()

            def encode_batch(self, x, dt):
                return torch.cat((x, x, dt[:, :, None]), -1)

        data = {
            "x": np.arange(7 * 3 * 4, dtype=np.float64).reshape(7, 3, 4) / 10,
            "dt": np.full((7, 3), 0.1, dtype=np.float64),
        }
        a, names = feature_banks(Stub(), data, chunk_size=2)
        data["y"] = np.full((7, 1), np.nan)
        b, other = feature_banks(Stub(), data, chunk_size=7)
        self.assertEqual(names, other)
        for name in a:
            torch.testing.assert_close(a[name], b[name])
        self.assertEqual(tuple(a["same_generator"].shape), (7, 20))


if __name__ == "__main__":
    unittest.main()
