"""Meaningful safeguards against timestep pseudo-replication and missing fits."""

import unittest

import numpy as np

from .statistics import matrix, paired_interval, validate_identity_grid


class StatisticsTests(unittest.TestCase):
    def test_identical_paired_policies_have_zero_uncertainty(self):
        result = paired_interval(np.zeros((5, 512)), replicates=1000)
        self.assertEqual(result["bootstrap_interval"], [0.0, 0.0])
        self.assertEqual(result["seed_level_t_interval"], [0.0, 0.0])

    def test_repeated_episodes_do_not_erase_fit_variability(self):
        values = np.repeat(np.arange(5, dtype=float)[:, None], 512, axis=1)
        result = paired_interval(values, replicates=1000)
        self.assertEqual(result["mean"], 2.0)
        self.assertGreater(result["bootstrap_interval"][1] - result["bootstrap_interval"][0], 1.5)
        self.assertEqual(result["fit_means"], list(range(5)))

    def test_missing_fit_or_trajectory_cannot_be_dropped(self):
        records = {("nominal", "A", fit, ep): {"quality": 1.0}
                   for fit in range(11, 16) for ep in range(8)}
        self.assertEqual(matrix(records, "nominal", "A", "quality").shape, (5, 8))
        del records["nominal", "A", 12, 1]
        with self.assertRaises(ValueError):
            matrix(records, "nominal", "A", "quality")

    def test_common_missing_indices_and_absent_registered_arm_fail_closed(self):
        records = {("nominal", "A", fit, ep): {"quality": 1.0,
                   "episode_seed": 2000000 + (fit - 11) * 10000 + ep,
                   "latent_seed": 920000000 + (fit - 11) * 10000 + ep}
                   for fit in range(11, 16) for ep in (0, 2)}
        # All fits omit the same index; observed-only rectangularity would pass.
        self.assertEqual(matrix(records, "nominal", "A", "quality").shape, (5, 2))
        audit = validate_identity_grid(records, [], {"status": "complete"},
                                       nominal_count=3, stress_count=1)
        self.assertEqual(audit["status"], "incomplete")
        self.assertIn(("nominal", "A", 11, 1), audit["missing_identities"])
        self.assertIn(("nominal", "B", 11, 0), audit["missing_identities"])

    def test_nominally_equal_indices_with_wrong_future_stream_are_rejected(self):
        record = {("nominal", "A", 11, 0): {"episode_seed": 2000001, "latent_seed": 0}}
        audit = validate_identity_grid(record, [], {}, nominal_count=1, stress_count=1)
        self.assertIn(("nominal", "A", 11, 0), audit["seed_mismatches"])


if __name__ == "__main__":
    unittest.main()
