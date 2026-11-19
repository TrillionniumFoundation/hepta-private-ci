"""Budget/split/report tests run without PyTorch as well as in tensor CI."""

import copy
import json
from pathlib import Path
import unittest
import tempfile
import shutil
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
    def test_resume_rebinds_copied_checkpoint_directory_to_verified_weights(self):
        from .. import benchmark
        config = json.loads((Path(__file__).parents[1]/"configs/smoke.json").read_text())
        config.update(models=["gru"], seeds=[0], train_steps=1, latency_repeats=1,
                      train_count=8, validation_count=4, test_count=4, batch_size=4)
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory)/'old.runs', Path(directory)/'copied.runs'
            first = benchmark.run(config, old)
            shutil.copytree(old, new)
            shutil.rmtree(old)
            with patch("hcsn.benchmark._run_one", side_effect=AssertionError('must reuse moved weights')):
                resumed = benchmark.run(config, new)
            actual = Path(resumed['runs'][0]['best_checkpoint'])
            self.assertTrue(actual.is_relative_to(new.resolve()))
            self.assertTrue(actual.exists())
            self.assertEqual(resumed['runs'][0]['best_checkpoint_sha256'],
                             first['runs'][0]['best_checkpoint_sha256'])
            index = json.loads(next(new.glob('*.json')).read_text())
            self.assertEqual(index['verified_weights'], str(actual))

    @unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch not installed")
    def test_source_change_quarantines_weights_before_any_reusable_cache(self):
        from .. import attempts, benchmark
        config = json.loads((Path(__file__).parents[1]/"configs/smoke.json").read_text())
        config.update(models=["gru"], seeds=[0], train_steps=1, latency_repeats=1,
                      train_count=8, validation_count=4, test_count=4, batch_size=4)
        snapshot = attempts.source_snapshot(Path(__file__).parents[1])
        with tempfile.TemporaryDirectory() as directory:
            with patch("hcsn.attempts.source_snapshot",
                       side_effect=[snapshot, snapshot, dict(snapshot, changed="injected")]):
                with self.assertRaisesRegex(RuntimeError, "quarantined"):
                    benchmark.run(config, directory)
            self.assertEqual(list(Path(directory).glob("*.json")), [])
            outcomes = list(Path(directory).glob("*.attempts/*.json"))
            terminal = [json.loads(p.read_text()) for p in outcomes if not p.name.endswith(".started.json")]
            self.assertEqual([r["result"]["status"] for r in terminal], ["invalidated"])
            self.assertEqual(len(list(Path(directory).glob("*.attempts/*.rejected.pt"))), 1)
            with patch("hcsn.benchmark._run_one", wraps=benchmark._run_one) as execute:
                restored = benchmark.run(config, directory)
                self.assertEqual(execute.call_count, 1)
            self.assertEqual(restored["attempt_accounting"]["invalidated"], 1)
            self.assertEqual(restored["attempt_accounting"]["completed"], 1)

    @unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch not installed")
    def test_retry_preserves_failed_attempt_budget_energy_and_failure_rate(self):
        import torch
        from ..benchmark import run
        config = json.loads((Path(__file__).parents[1]/"configs/smoke.json").read_text())
        config.update(models=["gru"], seeds=[0], train_steps=1, latency_repeats=1,
                      train_count=8, validation_count=4, test_count=4, batch_size=4)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(torch.optim.Adam, "step", side_effect=RuntimeError("injected optimizer failure")):
                failed = run(config, directory)
            self.assertEqual(failed["accounting"]["failed"], 1)
            immutable = {p: p.read_bytes() for p in Path(directory).glob("*.attempts/*.json")}
            retry = run(config, directory)
            self.assertEqual(retry["accounting"]["completed"], 1)
            self.assertEqual(retry["accounting"]["failed"], 0)
            stats = retry["attempt_accounting"]
            self.assertEqual((stats["total"], stats["completed"], stats["failed"]), (2, 1, 1))
            self.assertEqual(stats["execution_failure_rate"], .5)
            self.assertEqual(stats["training_failure_rate"], .5)
            self.assertEqual(stats["known_training_examples"], 8)
            self.assertEqual(stats["known_training_tokens"], 64)
            self.assertEqual(stats["energy_measured_attempts"]+stats["energy_missing_attempts"], 2)
            self.assertEqual(retry["summary"][0]["attempt_accounting"], stats)
            for path, contents in immutable.items():
                self.assertEqual(path.read_bytes(), contents)

    @unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch not installed")
    def test_interrupted_attempt_retains_unknown_budget_and_energy_on_resume(self):
        from ..benchmark import run
        config = json.loads((Path(__file__).parents[1]/"configs/smoke.json").read_text())
        config.update(models=["gru"], seeds=[0], train_steps=1, latency_repeats=1,
                      train_count=8, validation_count=4, test_count=4, batch_size=4)
        with tempfile.TemporaryDirectory() as directory:
            with patch("hcsn.benchmark._run_one", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    run(config, directory)
            retry = run(config, directory)
            stats = retry["attempt_accounting"]
            self.assertEqual((stats["total"], stats["interrupted"], stats["budget_unknown_attempts"]), (2, 1, 1))
            unknown = next(a["result"] for a in retry["runs"][0]["attempts"]
                           if a["result"]["status"] == "interrupted")
            self.assertIsNone(unknown["training_examples_seen"])
            self.assertIsNone(unknown["energy"]["joules_by_physical_counter"])

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
