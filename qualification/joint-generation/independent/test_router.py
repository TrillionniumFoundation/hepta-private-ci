import inspect
import unittest
from unittest.mock import patch

import numpy as np

from independent.router import (InputRouter, feature_work, fit_work, input_features, make_thumbnail,
                                prediction_work, priced_units, thumbnail_work)


class BudgetLedger:
    def __init__(self, limit):
        self.limit = limit
        self.spent = 0
        self.calls = []

    def charge_kernel(self, stage, kernel, **work):
        units = priced_units(work)
        if self.spent + units > self.limit:
            raise ValueError("declared arithmetic budget exceeded")
        self.spent += units
        self.calls.append((stage, kernel, work))


def random_inputs(rows=64):
    rng = np.random.default_rng(930123)
    words = np.column_stack((np.eye(4)[rng.integers(4, size=rows)],
                             np.eye(3)[rng.integers(3, size=rows)],
                             np.eye(3)[rng.integers(3, size=rows)]))
    full = np.column_stack((rng.uniform(0, 1, size=(rows, 192)), words))
    return make_thumbnail(full), full


class InputRouterTests(unittest.TestCase):
    def test_hand_drawn_features_and_thumbnail_are_actual_input_functions(self):
        full = np.zeros((1, 202))
        full[0, [192, 196, 199]] = 1
        image = full[:, :192].reshape(1, 8, 8, 3)
        image[:, 1:5, 1:3, 0] = 1
        ledger = BudgetLedger(10**9)
        low = make_thumbnail(full, ledger=ledger)
        observed = input_features(low, full, ledger=ledger)
        self.assertEqual(observed.shape, (1, 31))
        np.testing.assert_array_equal(observed[:, :10], full[:, 192:])
        self.assertAlmostEqual(observed[0, 10], 8 / 64)
        self.assertGreater(observed[0, 22], 0)
        self.assertGreater(observed[0, 28], 0)
        self.assertEqual(ledger.spent, priced_units(thumbnail_work(1)) + priced_units(feature_work(1)))
        self.assertGreater(priced_units(thumbnail_work(1)), 0)
        self.assertEqual(inspect.signature(InputRouter.route).parameters.keys(),
                         {"self", "low", "full", "threshold", "ledger", "stage"})

    def test_ridge_matches_normal_equations_and_roundtrip_keeps_decisions(self):
        low, full = random_inputs()
        features = input_features(low, full)
        gains = 0.2 * features[:, 0] - 0.3 * features[:, 1] + 0.1 * features[:, 22]
        ledger = BudgetLedger(10**9)
        dot_sizes = []
        actual_dot = np.dot

        def counted_dot(left, right):
            dot_sizes.append(left.size)
            return actual_dot(left, right)

        with patch("independent.router.np.dot", side_effect=counted_dot), \
                patch("independent.router.np.linalg.solve", side_effect=AssertionError("unpriced solver")):
            model = InputRouter.fit(low, full, gains, regularization=0.01, ledger=ledger)
        self.assertEqual(sum(dot_sizes), fit_work(64)["macs"] - 64 * (31 * 31 + 31))
        normalized = (features - model.mean) / model.scale
        gram = normalized.T @ normalized + np.eye(31) * 0.01 * len(full)
        expected = np.linalg.solve(gram, normalized.T @ (gains - gains.mean()))
        np.testing.assert_allclose(model.weights, expected, atol=1e-11, rtol=1e-11)
        restored = InputRouter.from_arrays(model.to_arrays())
        np.testing.assert_array_equal(model.route(low, full), restored.route(low, full))
        np.testing.assert_allclose(model.predict_gain(low, full), gains, atol=0.005)
        self.assertEqual(ledger.spent, priced_units(feature_work(64)) + priced_units(fit_work(64)))
        with self.assertRaises(TypeError):
            restored.route(low, full, labels=np.zeros(64))

    def test_route_budget_rejects_before_features_or_partial_charge(self):
        low, full = random_inputs(4)
        model = InputRouter.fit(low, full, np.array([-0.2, 0.1, 0.2, -0.1]))
        required = priced_units(feature_work(4)) + priced_units(prediction_work(4)) + 4
        ledger = BudgetLedger(required - 1)
        with patch("independent.router._features", side_effect=AssertionError("no unpaid feature work")):
            with self.assertRaisesRegex(ValueError, "budget exceeded"):
                model.route(low, full, ledger=ledger)
            fit_ledger = BudgetLedger(priced_units(feature_work(4)) + priced_units(fit_work(4)) - 1)
            with self.assertRaisesRegex(ValueError, "budget exceeded"):
                InputRouter.fit(low, full, np.zeros(4), ledger=fit_ledger)
        self.assertEqual((ledger.spent, ledger.calls), (0, []))
        self.assertEqual((fit_ledger.spent, fit_ledger.calls), (0, []))
        funded = BudgetLedger(required)
        model.route(low, full, ledger=funded)
        self.assertEqual(funded.spent, required)

    def test_malformed_inputs_targets_and_serialized_profiles_reject(self):
        low, full = random_inputs(4)
        for malformed in (full[:, :201], np.full_like(full, np.nan)):
            with self.assertRaises(ValueError):
                input_features(low, malformed)
        bad_words = full.copy()
        bad_words[0, 192] = 0.25
        with self.assertRaises(ValueError):
            input_features(low, bad_words)
        for gains, rate in ((np.zeros(3), 0.01), (np.full(4, np.inf), 0.01), (np.zeros(4), 0.5)):
            with self.assertRaises(ValueError):
                InputRouter.fit(low, full, gains, regularization=rate)
        model = InputRouter.fit(low, full, np.zeros(4))
        arrays = model.to_arrays()
        for name, replacement in (("router_profile", np.array([2])),
                                  ("router_scale", np.zeros(31)),
                                  ("router_weights", np.full(31, np.nan)),
                                  ("router_regularization", np.array([0.5])),
                                  ("router_intercept", np.zeros(2))):
            corrupted = {**arrays, name: replacement}
            with self.assertRaises(ValueError):
                InputRouter.from_arrays(corrupted)
        with self.assertRaises(ValueError):
            InputRouter.from_arrays({**arrays, "labels": np.zeros(1)})


if __name__ == "__main__":
    unittest.main()
