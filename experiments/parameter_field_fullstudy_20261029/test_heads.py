"""Numerical and filtration checks using synthetic banks only; opens no data."""

import unittest

import numpy as np

from .heads import choose, fit_head, history_feature, predict


class AdvantageHeadTests(unittest.TestCase):
    def bank(self):
        rng = np.random.default_rng(392)
        x = rng.normal(size=(9, 11))
        x[:, -1] = 7.
        y = rng.normal(size=(9, 4))
        y[:, 2] = 0.
        fit = np.arange(9) < 6
        return x, y, fit, ~fit

    def test_dual_matches_independent_primal_ridge_with_free_intercept(self):
        x, y, fit, cal = self.bank()
        head = fit_head(x, y, fit, cal)
        z = (x[fit] - x[fit].mean(0)) / np.maximum(x[fit].std(0), 1e-8)
        centered_y = y[fit] - y[fit].mean(0)
        expected = np.linalg.solve(z.T @ z + np.eye(x.shape[1]), z.T @ centered_y)
        np.testing.assert_allclose(head["coefficients"], expected, rtol=1e-11, atol=1e-11)
        np.testing.assert_allclose(head["intercept"], y[fit].mean(0), rtol=1e-13, atol=1e-13)
        self.assertEqual(head["diagnostics"]["constant_coordinates"], 1)
        self.assertTrue(np.isfinite(head["coefficients"]).all())
        np.testing.assert_array_equal(head["coefficients"][:, 2], 0.)
        self.assertEqual(head["intercept"][2], 0.)

    def test_calibration_cannot_change_fit_and_threshold_is_one_sided(self):
        x, y, fit, cal = self.bank()
        first = fit_head(x, y, fit, cal)
        changed_x, changed_y = x.copy(), y.copy()
        changed_x[cal] += 11.
        changed_y[cal, 0] -= 31.
        second = fit_head(changed_x, changed_y, fit, cal)
        for key in ("mean", "scale", "coefficients", "intercept"):
            np.testing.assert_array_equal(first[key], second[key])
        predicted = np.asarray([predict(second, row)[0] for row in changed_x[cal]])
        expected = max(0., float((predicted - changed_y[cal])[:, [0, 1, 3]].max()))
        self.assertEqual(second["threshold"], expected)
        self.assertNotEqual(first["threshold"], second["threshold"])
        self.assertFalse(second["certificate"])
        self.assertTrue(second["diagnostics"]["calibration_rows_dependent"])

    def fixed_head(self, scores, threshold):
        return {"mean": np.zeros(1), "scale": np.ones(1),
                "coefficients": np.zeros((1, 4)), "intercept": np.asarray(scores, dtype=float),
                "threshold": threshold, "baseline": 2, "fit_max_standardized_norm": 1.}

    def test_gate_uses_unique_maximum_and_strict_threshold(self):
        cases = (([.5, .4, 0., -.1], .5, 2),
                 ([.5, .4, 0., -.1], np.nextafter(.5, 0.), 0),
                 ([.5, .5, 0., -.1], .1, 2),
                 ([0., 0., 0., 0.], 0., 2),
                 ([-1., -2., 0., -3.], 0., 2))
        for scores, threshold, expected in cases:
            with self.subTest(scores=scores, threshold=threshold):
                action, receipt = choose(self.fixed_head(scores, threshold), [0.])
                self.assertEqual(action, expected)
                self.assertEqual(receipt["override"], expected != 2)
                self.assertFalse(receipt["certificate"])
        with self.assertRaises(ValueError):
            choose(self.fixed_head([1., 0., 0., 0.], 0.), [0.], baseline=3)

    def test_invalid_training_partitions_and_targets_are_rejected(self):
        x, y, fit, cal = self.bank()
        cases = [(x, y, fit, fit), (x, y, np.zeros(9, dtype=bool), cal)]
        bad_x, bad_y = x.copy(), y.copy()
        bad_x[0, 0] = np.nan
        bad_y[0, 2] = 1e-12
        cases += [(bad_x, y, fit, cal), (x, bad_y, fit, cal)]
        for arguments in cases:
            with self.subTest(arguments=str(arguments)[:80]), self.assertRaises(ValueError):
                fit_head(*arguments)
        for baseline in (-1, 4, True, 1.5):
            with self.subTest(baseline=baseline), self.assertRaises(ValueError):
                fit_head(x, np.zeros_like(y), fit, cal, baseline=baseline)

    def test_deployment_rejects_missing_and_nonfinite_observation(self):
        head = self.fixed_head([1., 0., 0., 0.], 0.)
        for feature in ([], [0., 1.], [np.nan], [np.inf]):
            with self.subTest(feature=feature), self.assertRaises(ValueError):
                choose(head, feature)


class HistoryFiltrationTests(unittest.TestCase):
    def row(self, action=3):
        return {"field": np.arange(12, dtype=float).tolist(), "action": action,
                "accepted": True, "scheduled_microsteps": 48}

    def test_only_completed_observations_and_current_field_are_encoded(self):
        current = np.arange(12, dtype=float) + 20
        vector = history_feature([self.row()], current).reshape(6, 19)
        np.testing.assert_array_equal(vector[0, :12], np.arange(12))
        np.testing.assert_array_equal(vector[0, 12:16], [0., 0., 0., 1.])
        np.testing.assert_array_equal(vector[0, 16:], [1., 1., 1.])
        np.testing.assert_array_equal(vector[1, :12], current)
        np.testing.assert_array_equal(vector[1, 12:18], 0.)
        self.assertEqual(vector[1, 18], 1.)
        np.testing.assert_array_equal(vector[2:], 0.)
        self.assertEqual(vector.size, 114)

    def test_initial_and_last_legal_decision_keep_future_slots_empty(self):
        current = np.zeros(12)
        first = history_feature([], current).reshape(6, 19)
        self.assertEqual(first[0, 18], 1.)
        np.testing.assert_array_equal(first[1:], 0.)
        last = history_feature([self.row(i % 4) for i in range(5)], current).reshape(6, 19)
        np.testing.assert_array_equal(last[-1, 12:18], 0.)
        np.testing.assert_array_equal(last[:, 18], 1.)

    def test_invalid_actions_cannot_silently_overwrite_other_coordinates(self):
        for action in (-1, 4, True, 1.5):
            with self.subTest(action=action), self.assertRaises(ValueError):
                history_feature([self.row(action)], np.zeros(12))

    def test_invalid_history_and_current_values_are_rejected(self):
        variants = [{"field": [0.] * 11}, {"field": [np.nan] * 12},
                    {"accepted": "yes"}, {"scheduled_microsteps": -48},
                    {"scheduled_microsteps": 47}, {"extra": 1}]
        for change in variants:
            with self.subTest(change=change), self.assertRaises(ValueError):
                history_feature([{**self.row(), **change}], np.zeros(12))
        for current in ([0.] * 11, [np.inf] * 12):
            with self.subTest(current=current), self.assertRaises(ValueError):
                history_feature([], current)
        with self.assertRaises(ValueError):
            history_feature([self.row()] * 6, np.zeros(12))


if __name__ == "__main__":
    unittest.main()
