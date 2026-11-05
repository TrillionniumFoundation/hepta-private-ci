"""Budget/split/report tests run without PyTorch as well as in tensor CI."""

import copy
import json
from pathlib import Path
import unittest

import numpy as np

from ..benchmark import EnergyCounter, aggregate, make_dataset, validate_config


class DatasetTests(unittest.TestCase):
    def test_recall_and_adding_labels_follow_task_definition(self):
        x, y = make_dataset("delayed_recall", 32, 8, 17)
        np.testing.assert_array_equal(y[:, 0], x[:, 0, 0])
        np.testing.assert_array_equal(x[..., 1].sum(1), np.ones(32))
        x, y = make_dataset("adding", 32, 8, 17)
        np.testing.assert_allclose(y[:, 0], (x[..., 0]*x[..., 1]).sum(1), rtol=1e-6)
        np.testing.assert_array_equal(x[..., 1].sum(1), np.full(32, 2))

    def test_same_seed_reproduces_and_different_split_seed_changes_examples(self):
        first = make_dataset("delayed_recall", 16, 8, 23)
        repeat = make_dataset("delayed_recall", 16, 8, 23)
        different = make_dataset("delayed_recall", 16, 8, 24)
        for a, b in zip(first, repeat):
            np.testing.assert_array_equal(a, b)
        self.assertFalse(np.array_equal(first[0], different[0]))

    def test_bad_dataset_and_budget_rejected(self):
        with self.assertRaises(ValueError):
            make_dataset("adding", 3, 2, 0)
        with self.assertRaises(ValueError):
            make_dataset("unknown", 3, 8, 0)
        config = json.loads((Path(__file__).parents[1]/"configs/smoke.json").read_text())
        validate_config(config)
        for key, value in (("train_steps", 0), ("seeds", [1, 1]), ("dt", 0), ("dt", float("nan"))):
            invalid = copy.deepcopy(config)
            invalid[key] = value
            with self.assertRaises(ValueError):
                validate_config(invalid)

    def test_energy_counter_wraps_without_estimating_missing_measurements(self):
        meter = object.__new__(EnergyCounter)
        readings = iter([9.0, 1.0, 3.5])
        meter.sources = [("physical_counter", lambda: next(readings), 10.0)]
        meter.before, meter.measured, meter.invalid, meter.reason = {}, {}, set(), []
        for _ in range(3):
            meter._sample()
        self.assertEqual(meter.measured, {"physical_counter": 4.5})
        # A failed hardware read removes that measurement, never fills a guess.
        meter._sample()
        self.assertEqual(meter.measured, {})
        self.assertEqual(meter.invalid, {"physical_counter"})

    def test_unavailable_is_not_counted_as_a_failed_training_run(self):
        base = dict(task="recall", model="a", test_mse=0.2, training_examples_per_second=2,
                    inference_examples_per_second=3, latency_p50_ms=4, latency_p95_ms=5)
        runs = [dict(base, status="completed", training_status="completed"),
                dict(task="recall", model="a", status="failed", training_status="failed"),
                dict(task="recall", model="a", status="unavailable")]
        result = aggregate(runs)[0]
        self.assertEqual((result["completed_seeds"], result["failed_seeds"], result["unavailable_seeds"]), (1, 1, 1))
        self.assertEqual(result["training_failure_rate"], 0.5)
        self.assertEqual(result["test_mse_mean"], 0.2)
        self.assertIsNone(result["test_mse_seed_std"])
        only_missing = aggregate([runs[-1]])[0]
        self.assertIsNone(only_missing["training_failure_rate"])
        self.assertIsNone(only_missing["test_mse_mean"])


if __name__ == "__main__":
    unittest.main()
