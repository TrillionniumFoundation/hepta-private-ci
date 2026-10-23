import unittest
from unittest.mock import patch

import numpy as np

from independent.accounting import BudgetExceeded, WorkLedger
from independent.diagnose_decisions import (decision_metrics, ridge_oof_fit_predict,
                                          ridge_work, source_folds, probe_content)


class DecisionDiagnosticTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(918231)
        self.x = rng.normal(size=(48, 5))
        self.raw = self.x @ np.array([.2, -.3, .1, .04, -.07])
        self.fit = np.arange(48) < 36
        self.hold = ~self.fit

    def test_native_probe_uses_public_constructor_keywords_and_two_calls(self):
        inputs = np.zeros((3, 202))
        model, ledger, library = object(), WorkLedger("native-hand-dispatch"), "unused.so"
        outputs = tuple(np.full((3, width), index, dtype=float)
                        for index, width in enumerate((12, 12, 32, 12, 12)))
        with patch("independent.diagnose_decisions.NativeGenerator", autospec=True) as constructor:
            generator = constructor.return_value
            generator.forward_low_state.return_value = outputs[:3]
            generator.forward_full.return_value = outputs[3:]
            actual = probe_content(model, library, inputs, ledger)
            constructor.assert_called_once_with(model, ledger=ledger, stage="content_probe",
                                                 prepare_low=False, library_path=library)
            generator.forward_low_state.assert_called_once_with(inputs, ledger, "content_probe")
            generator.forward_full.assert_called_once_with(inputs, ledger, "content_probe")
        for observed, expected in zip(actual, outputs):
            self.assertIs(observed, expected)

    def test_mse_is_current_unweighted_ridge_and_hold_labels_do_not_fit(self):
        ledger = WorkLedger("mse-handmade")
        prediction, receipt, arrays = ridge_oof_fit_predict(self.x, self.raw, np.ones(48),
            self.fit, self.hold, binary=False, ledger=ledger)
        z = (self.x[self.fit]-arrays["mean"])/arrays["scale"]
        expected = np.linalg.solve(z.T @ z + np.eye(5)*.001*36,
                                  z.T @ (self.raw[self.fit]-self.raw[self.fit].mean()))
        np.testing.assert_allclose(arrays["coefficients"], expected, atol=1e-13)
        altered = self.raw.copy()
        altered[self.hold] += 1000
        again, _, same = ridge_oof_fit_predict(self.x, altered, np.ones(48), self.fit, self.hold,
                                               binary=False, ledger=WorkLedger("mse-again"))
        np.testing.assert_array_equal(prediction, again)
        for name in arrays:
            np.testing.assert_array_equal(arrays[name], same[name])
        self.assertEqual((receipt["fit_rows"], receipt["hold_rows"]), (36, 12))

    def test_weighted_binary_matches_unpenalized_intercept_normal_equations(self):
        price = .03
        labels, weights = (self.raw > price).astype(float), np.abs(self.raw-price)
        prediction, _, arrays = ridge_oof_fit_predict(self.x, labels, weights,
            self.fit, self.hold, binary=True, ledger=WorkLedger("weighted-handmade"))
        z = (self.x[self.fit]-arrays["mean"])/arrays["scale"]
        design = np.column_stack((np.ones(len(z)), z))
        ww = weights[self.fit]
        penalty = np.diag(np.r_[0., np.full(5, .001*ww.sum())])
        coefficients = np.linalg.solve(design.T @ (ww[:, None]*design)+penalty,
                                       design.T @ (ww*labels[self.fit]))
        actual = np.r_[arrays["intercept"][0]-arrays["center"] @ arrays["coefficients"],
                       arrays["coefficients"]]
        np.testing.assert_allclose(actual, coefficients, atol=1e-12)
        held = np.column_stack((np.ones(self.hold.sum()),
                                (self.x[self.hold]-arrays["mean"])/arrays["scale"]))
        np.testing.assert_allclose(prediction, np.clip(held @ coefficients, 0, 1), atol=1e-12)

    def test_source_folds_keep_physical_sources_together_and_ignore_row_order(self):
        sources = [f"source-{scene}-{index}" for scene in range(12) for index in range(4) for _ in range(2)]
        scenes = np.repeat(np.arange(12), 8)
        data = {"split": "train", "source_ids": sources, "source_scenes": scenes}
        folds, receipt = source_folds(data)
        self.assertEqual([row["rows"] for row in receipt["folds"]], [24]*4)
        self.assertTrue(all(set(row["source_class_counts"].values()) == {1} for row in receipt["folds"]))
        original = dict(zip(sources, folds.tolist()))
        order = np.random.default_rng(12).permutation(len(sources))
        shuffled, again = source_folds({"split": "train", "source_ids": [sources[i] for i in order],
                                       "source_scenes": scenes[order]})
        self.assertEqual(original, dict(zip([sources[i] for i in order], shuffled.tolist())))
        self.assertEqual(receipt["source_fold_sha256"], again["source_fold_sha256"])
        for source in set(sources):
            self.assertEqual(len(set(folds[np.asarray(sources) == source])), 1)
        with self.assertRaises(ValueError):
            source_folds({**data, "split": "validation"})

    def test_metrics_use_source_equal_regret_and_report_wrong_stop_concentration(self):
        delta = np.array([.6, .3, -.2, .05])
        low = np.full(4, .2)
        action = np.array([False, True, False, False])
        report = decision_metrics(action, delta, low+delta, low, .1, ["a", "a", "b", "c"])
        self.assertAlmostEqual(report["regret"], .25/3)
        self.assertAlmostEqual(report["false_stop_lost_raw"], .1)
        self.assertEqual((report["false_stop_count"], report["false_stop_source_count"]), (1, 1))
        self.assertEqual((report["false_stop_top1_net_fraction"], report["false_stop_top5_raw_fraction"]), (1., 1.))
        oracle = decision_metrics(delta > .1, delta, low+delta, low, .1, ["a", "a", "b", "c"])
        self.assertEqual(oracle["regret"], 0.)
        self.assertIsNone(oracle["false_stop_top1_net_fraction"])

    def test_ridge_budget_rejects_before_solver_and_does_not_partially_charge(self):
        work = ridge_work(36, 5, 12, binary=True)
        required = WorkLedger("estimate").estimate_kernel(**work)
        ledger = WorkLedger("short", total_cap=required-1)
        before = ledger.snapshot()
        with patch("independent.diagnose_decisions.np.linalg.solve", side_effect=AssertionError("unpaid solve")):
            with self.assertRaises(BudgetExceeded):
                ridge_oof_fit_predict(self.x, (self.raw > 0).astype(float), np.abs(self.raw),
                    self.fit, self.hold, binary=True, ledger=ledger)
        self.assertEqual(ledger.snapshot(), before)

    def test_zero_weight_and_invalid_fold_inputs_are_not_silently_repaired(self):
        with self.assertRaisesRegex(ValueError, "zero training regret weight"):
            ridge_oof_fit_predict(self.x, (self.raw > 0).astype(float), np.zeros(48),
                self.fit, self.hold, binary=True, ledger=WorkLedger("zero"))
        with self.assertRaises(ValueError):
            ridge_oof_fit_predict(self.x, self.raw, np.ones(48), self.fit, self.fit,
                binary=False, ledger=WorkLedger("overlap"))
        with self.assertRaises(ValueError):
            source_folds({"split": "test", "source_ids": [], "source_scenes": []})


if __name__ == "__main__":
    unittest.main()
