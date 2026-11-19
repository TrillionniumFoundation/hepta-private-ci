"""Research-only generator comparator invariants and source-independent truth."""

import unittest

import torch

from proposals.hcsn_semigroup_v1.semigroup_candidate import (
    continuum_hit_transform,
    discounted_hit_transform,
    generator_trial,
    probe,
)


class GeneratorComparatorTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_five_drift_regimes_and_interior_grid_refinement(self):
        a = probe(128)
        b = probe(256)
        for first, second in zip(a["rows"], b["rows"]):
            self.assertEqual(first["mu"], second["mu"])
            self.assertLess(second["interior_max_absolute_error_x_lt_2"], 0.0002)
            self.assertLess(
                second["interior_max_absolute_error_x_lt_2"],
                first["interior_max_absolute_error_x_lt_2"],
            )
            self.assertLess(second["subgenerator_row_balance"], 1e-10)
            self.assertGreaterEqual(second["min_laplace"], 0)
            self.assertLessEqual(second["max_laplace"], 1)
        self.assertLess(a["semigroup_16cell_2x_0p001_max_abs"], 1e-8)
        self.assertFalse(a["production_admission"])

    def test_substochastic_semigroup_and_no_time_step_in_generator(self):
        trial = generator_trial(16, 2.0, -0.12, 0.35)
        self.assertLess(float((trial.q.sum(-1) + trial.absorption).abs().max()), 1e-12)
        time_a, time_b = 0.001, 0.002
        p = torch.matrix_exp(time_a * trial.q)
        q = torch.matrix_exp(time_b * trial.q)
        direct = torch.matrix_exp((time_a + time_b) * trial.q)
        self.assertLess(float((p @ q - direct).abs().max()), 1e-8)
        self.assertGreaterEqual(float(p.min()), -1e-12)
        self.assertLessEqual(float(p.sum(-1).max()), 1 + 1e-10)

    def test_strong_peclet_and_invalid_parameters(self):
        for mu in (-2.0, 2.0):
            trial = generator_trial(16, 8.0, mu, 0.05)
            value = discounted_hit_transform(trial, 0.15)
            self.assertTrue(bool(torch.isfinite(value).all()))
            self.assertGreaterEqual(float(value.min()), 0)
        for args in ((3, 4.8, 0, 0.35), (16, 9, 0, 0.35), (16, 4.8, 0, 0.0)):
            with self.assertRaises(ValueError):
                generator_trial(*args)
        with self.assertRaises(ValueError):
            discounted_hit_transform(generator_trial(8, 2.0, 0, 0.35), 0)

    def test_continuum_reference_monotonic_and_crosses_zero_drift(self):
        centers = torch.tensor([0.01, 0.1, 1.0], dtype=torch.float64)
        for mu in (-0.2, 0.0, 0.2):
            value = continuum_hit_transform(centers, mu, 0.35, 0.15)
            self.assertTrue(bool(torch.all(value[1:] < value[:-1])))
            self.assertGreater(float(value.min()), 0)
            self.assertLess(float(value.max()), 1)


if __name__ == "__main__":
    unittest.main()
