"""Readout lifecycle checks and optional integration with the real native binary."""

import argparse
import copy
import inspect
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .controls import choose, fit_readout, history_features, native_features
from .native_bridge import NativeBridge


class ReadoutTests(unittest.TestCase):
    def setUp(self):
        self.train = np.zeros((12, 40))
        self.dev = np.full((4, 40), 7.0)
        self.train_returns = np.ones((12, 5))
        self.dev_returns = np.ones((4, 5))

    def test_exact_prediction_ties_and_unpenalized_constant_intercept(self):
        model = fit_readout(self.train, self.train_returns, self.dev, self.dev_returns)
        actions = choose(json.loads(json.dumps(model)), self.dev)
        np.testing.assert_array_equal(actions, np.zeros(4, dtype=np.int64))
        coefficient = np.asarray(model["coefficient"])
        np.testing.assert_allclose(coefficient[:-1], 0, atol=1e-14)
        np.testing.assert_allclose(coefficient[-1], 1, atol=1e-14)

    def test_normalizer_fits_training_and_never_shifted_development(self):
        rng = np.random.default_rng(221)
        training = rng.normal(2, 0.5, size=(64, 40))
        development = rng.normal(200, 0.5, size=(8, 40))
        returns = np.tile(np.array([0.2, -1, -1, -1, -1]), (64, 1))
        model = fit_readout(training, returns, development, returns[:8])
        np.testing.assert_allclose(model["normalizer"]["mean"], training.mean(0))
        self.assertLess(max(model["normalizer"]["mean"]), 3)
        np.testing.assert_array_equal(choose(model, development), np.zeros(8, dtype=np.int64))

    def test_nonfinite_inputs_and_frozen_coefficients_are_rejected(self):
        bad = self.train.copy()
        bad[0, 3] = np.nan
        with self.assertRaises(ValueError):
            fit_readout(bad, self.train_returns, self.dev, self.dev_returns)
        bad_return = self.train_returns.copy()
        bad_return[0, 2] = np.inf
        with self.assertRaises(ValueError):
            fit_readout(self.train, bad_return, self.dev, self.dev_returns)
        model = fit_readout(self.train, self.train_returns, self.dev, self.dev_returns)
        bad_model = copy.deepcopy(model)
        bad_model["coefficient"][-1][0] = float("nan")
        with self.assertRaises(ValueError):
            choose(bad_model, self.dev)

    def test_runtime_selection_has_no_target_argument_or_test_refit(self):
        self.assertEqual(tuple(inspect.signature(choose).parameters), ("model", "X"))
        model = fit_readout(self.train, self.train_returns, self.dev, self.dev_returns)
        before = json.dumps(model, sort_keys=True)
        choose(model, self.dev)
        self.assertEqual(before, json.dumps(model, sort_keys=True))
        with self.assertRaises(TypeError):
            choose(model, self.dev, targets=self.dev_returns)
        with self.assertRaises(TypeError):
            native_features(None, np.zeros((1, 8)), np.zeros((1, 8)), "case", targets=[0])

    def test_history_retains_earlier_event_when_current_observation_matches(self):
        first = np.array([[0.1] * 8, [0.9] * 8])
        second = np.full((2, 8), 0.5)
        history = history_features(first, second)
        np.testing.assert_array_equal(history[:, :8], first)
        np.testing.assert_array_equal(history[:, 8:16], second)
        self.assertFalse(np.array_equal(history[0], history[1]))
        first[0, 0] = np.nan
        with self.assertRaises(ValueError):
            history_features(first, second)


class NativeExecutionTests(unittest.TestCase):
    build_receipt = None

    def test_real_two_event_state_and_reset_with_persisted_receipts(self):
        if self.build_receipt is None:
            self.skipTest("Pass --native-build-receipt to run the actual native kernel integration")
        build = json.loads(Path(self.build_receipt).read_text())
        first = np.array([[0.1] * 8, [0.9] * 8])
        second = np.full((2, 8), 0.6)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stateful.jsonl"
            with NativeBridge(build["binary"], build["binary_sha256"]) as bridge:
                stateful = native_features(bridge, first, second, "same-scope", receipt_path=path)
                reset = native_features(bridge, first, second, "same-scope", reset=True)
                self.assertEqual(bridge.request_count, 4)
                self.assertEqual(bridge.last_feature_batch["original_sparse_tick_calls"], 4)
            self.assertFalse(np.array_equal(stateful[0], stateful[1]))
            np.testing.assert_array_equal(reset[0], reset[1])
            self.assertFalse(np.array_equal(stateful, reset))
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row["native"]["original_sparse_tick_calls"] == 2 for row in rows))
            self.assertTrue(all(row["native"]["ticks"][1]["fresh_public_observation"] for row in rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-build-receipt")
    arguments, remaining = parser.parse_known_args()
    NativeExecutionTests.build_receipt = arguments.native_build_receipt
    unittest.main(argv=["controls_tests", *remaining])
