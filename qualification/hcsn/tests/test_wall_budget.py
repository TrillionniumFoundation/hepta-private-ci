"""Exercise real optimizer updates across validation/checkpoint deadlines."""

import importlib.util
import itertools
import time
import types
import unittest
from unittest.mock import patch

import numpy as np


@unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch not installed")
class WallBudgetTests(unittest.TestCase):
    def test_late_validation_and_late_copy_cannot_select_updated_weights(self):
        import torch
        from ..benchmark import _run_one

        config = dict(hidden_size=8, dt=0.1, batch_size=4, train_steps=100,
                      learning_rate=0.003, training_wall_seconds=4,
                      validation_interval_seconds=1, length=4, latency_repeats=1)
        inputs = np.ones((8, 4, 2), dtype=np.float32)
        targets = np.ones((8, 1), dtype=np.float32)
        splits = [inputs, targets]*3
        for late_stage, times in (
            ("validation", [0, 0.1, 0.2, 0.3, 2, 4.1, 4.2, 4.3, 4.4]),
            ("checkpoint_copy", [0, 0.1, 0.2, 0.3, 2, 3, 4.1, 4.2, 4.3, 4.4]),
        ):
            with self.subTest(late_stage=late_stage):
                ticks = itertools.chain(times, itertools.count(5))
                clock = types.SimpleNamespace(perf_counter=lambda: next(ticks),
                                              process_time=time.process_time)
                with patch("hcsn.benchmark.time", clock):
                    record = _run_one(config, "adding", "matched_gate", 41,
                                      splits, torch.device("cpu"), torch)
                self.assertEqual(record["status"], "completed", record)
                self.assertEqual(record["training_steps_completed"], 1)
                self.assertEqual(record["optimizer_steps_within_wall_budget"], 1)
                self.assertEqual([point["eligible"] for point in record["validation_curve"]],
                                 [True, False])
                self.assertLess(record["validation_curve"][1]["mse"],
                                record["validation_curve"][0]["mse"])
                self.assertEqual(record["training_wall_budget"], dict(
                    seconds=4, filled=True, overrun_seconds=0.40000000000000036,
                    scope="initial validation, training, periodic validation and checkpoint copies",
                    best_checkpoint_step=0, best_checkpoint_wall_seconds=0.2,
                    best_checkpoint_eligible=True))
                self.assertTrue(all(value == 0 for value in record["selected_parameter_delta_l2"].values()))
                self.assertGreater(record["gradient_l2_max_by_parameter"]["encoder.raw_financial"], 0)
                self.assertAlmostEqual(record["test_mse"], record["validation_curve"][0]["mse"])


if __name__ == "__main__":
    unittest.main()
