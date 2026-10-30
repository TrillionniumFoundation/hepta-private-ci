"""Behavioral checks use a dedicated seed namespace, never confirmation draws."""

import math
import unittest
from unittest.mock import patch

import numpy as np

from . import task_study as task


class TaskTests(unittest.TestCase):
    def test_hazard_likelihood_gradients(self):
        records = [("hit", 0.19, 1.0), ("hit", 1.3, 1.0), ("no_hit", 0.6, 1.0), ("no_hit", 2.4, 1.0)]
        parameters = np.array([0.63, 1.4, 0.85])
        for family in ["cure_weibull", "cure_loglogistic"]:
            _, analytic = task.hazard_objective(parameters, family, records)
            numerical = []
            for i in range(3):
                direction = np.eye(3)[i] * 1e-6
                upper = task.hazard_objective(parameters + direction, family, records)[0]
                lower = task.hazard_objective(parameters - direction, family, records)[0]
                numerical.append((upper - lower) / 2e-6)
            np.testing.assert_allclose(analytic, numerical, atol=2e-7, rtol=2e-6)

    def test_independent_simulator_and_hidden_cancellation(self):
        cfg = task.protocol()
        rng = np.random.default_rng(91001)
        hit, cancellation = task.sample_contracts(rng, 0, 20000, cfg)
        horizon = 1.2
        empirical = np.mean((hit <= horizon) & (hit < cancellation))
        parameters = cfg["truth"][0]
        expected = math.exp(task.log_discounted_hit(1.0, horizon, *parameters))
        self.assertLess(abs(empirical - expected), 0.015)
        self.assertGreater(np.mean((cancellation < hit) & (cancellation < horizon)), 0.05)

    def test_hidden_cancellation_waits_to_horizon(self):
        cfg = dict(task.protocol(), max_queries=1)
        episode = {"label": 1, "context": 0.5, "latent_hit": [0.1], "latent_cancel": [0.05]}
        requested_times = []

        def law(model, class_id, times, config):
            requested_times.extend(times)
            return np.array([0.4]), np.array([0.7])

        with patch.object(task, "choose_horizon", return_value=0.7), patch.object(task, "model_law", side_effect=law):
            result = task.rollout({}, episode, {}, cfg)
        self.assertEqual(requested_times, [0.7, 0.7])
        self.assertEqual((result["observed_hits"], result["queries"], result["elapsed_task_time"]), (0, 1, 0.7))
        self.assertAlmostEqual(result["resource_cost"], cfg["query_cost"] + 0.7 * cfg["wait_cost_per_time"])

    def test_probability_tables_and_budgeted_action(self):
        cfg = task.protocol()
        model = {"family": "cure_weibull", "parameters": [[0.7, 1.5, 0.6], [0.7, 1.5, 1.2]]}
        tables, _ = task.controller_tables(model, cfg)
        for table in tables.values():
            np.testing.assert_allclose(table["law"].sum(axis=1), np.ones(2), atol=1e-13)
            self.assertTrue(np.all(table["law"] >= 0))
        self.assertIsNone(task.choose_horizon(0.5, 0.1, tables, cfg))
        self.assertIsNone(task.choose_horizon(1.0, 3.2, tables, cfg))

    def test_confirmation_refuses_before_drawing_data(self):
        cfg = task.protocol()
        bundle = {"source_sha256": task.source_hashes(cfg), "protocol_sha256": task.digest(cfg), "seeds": []}
        with patch.object(task, "episode_bank") as generator:
            with self.assertRaisesRegex(ValueError, "frozen bundle path"):
                task.evaluate_bundle(bundle, "confirm", cfg)
            generator.assert_not_called()

    def test_paired_episode_bank_reproducibility(self):
        cfg = task.protocol()
        first = task.episode_bank(91003, 12, cfg)
        second = task.episode_bank(91003, 12, cfg)
        shifted = task.episode_bank(91003, 12, cfg, regime="ood")
        self.assertEqual(first, second)
        self.assertNotEqual(task.digest(first), task.digest(shifted))


if __name__ == "__main__":
    unittest.main()
