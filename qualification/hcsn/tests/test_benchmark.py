"""Budget/split/report tests run without PyTorch as well as in tensor CI."""

import copy
import json
from pathlib import Path
import unittest
import tempfile
import importlib.util
from unittest.mock import patch

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

    @unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch not installed")
    def test_completed_run_resume_verifies_weights_and_exact_budget(self):
        from ..benchmark import run
        config = json.loads((Path(__file__).parents[1]/"configs/smoke.json").read_text())
        config.update(models=["gru"], seeds=[0], train_steps=1, latency_repeats=1,
                      train_count=8, validation_count=4, test_count=4, batch_size=4)
        with tempfile.TemporaryDirectory() as directory:
            first = run(config, directory)
            self.assertEqual(first["accounting"], dict(requested=1, unique_records=1,
                                                    completed=1, failed=0, unavailable=0))
            with patch("hcsn.benchmark._run_one", side_effect=AssertionError("reran completed run")):
                self.assertEqual(run(config, directory)["runs"], first["runs"])
            weights = Path(first["runs"][0]["best_checkpoint"])
            weights.write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "corrupted"):
                run(config, directory)
            config["train_steps"] = 2
            changed = run(config, directory)
            self.assertEqual(changed["runs"][0]["training_examples_seen"], 8)
            self.assertNotEqual(changed["runs"][0]["best_checkpoint"], str(weights))

    @unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch not installed")
    def test_trained_grid_audit_reproduces_encoder_and_preserves_refractory(self):
        import torch
        from ..audit_population import trace
        from ..baselines import make_encoder
        torch.manual_seed(3)
        encoder = make_encoder("population_flux", 2, 2, dt=.1)
        readout = torch.nn.Linear(2, 1)
        inputs = torch.randn(2, 4, 2)
        with torch.no_grad():
            expected = encoder(inputs, dt=.1)
        prediction, outputs, measurements = trace(encoder, readout, inputs, 1)
        torch.testing.assert_close(outputs, expected)
        torch.testing.assert_close(prediction, readout(expected[:, -1]))
        _, _, refined = trace(encoder, readout, inputs, 2)
        self.assertAlmostEqual(measurements["effective_refractory"], .3)
        self.assertAlmostEqual(refined["effective_refractory"], .3)
        self.assertLess(refined["maximum_mass_error"], 1e-5)

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
