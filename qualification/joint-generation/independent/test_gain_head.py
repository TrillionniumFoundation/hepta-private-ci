import io
import unittest
from unittest.mock import patch

import numpy as np

from control import Controller
from independent.accounting import BudgetExceeded, WorkLedger
from independent.gain_head import AffineGainHead, ARRAY_KEYS, KIND, fit_work, head_work, load_controller


class AffineGainHeadTests(unittest.TestCase):
    def fixture(self):
        rng = np.random.default_rng(42)
        hidden = rng.normal(size=(24, 4))
        instruction = rng.normal(size=(24, 10))
        instruction[:, 0] = 1.0  # A constant feature exercises the std floor.
        target = 0.06 * hidden[:, 1] - 0.03 * instruction[:, 2] + 0.02
        plan = {"controller": {"gain_head": KIND, "ridge_regularization": 0.001}}
        return hidden, instruction, target, plan

    def test_fit_matches_ordinary_ridge_without_touching_supplied_state(self):
        hidden, instruction, target, plan = self.fixture()
        copies = [value.copy() for value in (hidden, instruction, target)]
        ledger = WorkLedger("hand-fixture")
        head, receipt = AffineGainHead.fit(hidden, instruction, target, plan, 11, ledger)
        features = np.concatenate((hidden, instruction), axis=1)
        mean, scale = features.mean(0), np.maximum(features.std(0), 0.05)
        normalized = (features - mean) / scale
        gram = normalized.T @ normalized + 0.001 * len(features) * np.eye(features.shape[1])
        weights = np.linalg.solve(gram, normalized.T @ (target - target.mean()))
        np.testing.assert_allclose(head.mean, mean, rtol=0, atol=1e-14)
        np.testing.assert_allclose(head.scale, scale, rtol=0, atol=1e-14)
        np.testing.assert_allclose(head.weights, weights, rtol=0, atol=1e-12)
        np.testing.assert_allclose(head.predict_state(hidden, instruction),
            np.clip(normalized @ weights + target.mean(), target.min(), target.max()), rtol=0, atol=1e-13)
        for value, before in zip((hidden, instruction, target), copies):
            np.testing.assert_array_equal(value, before)
        self.assertEqual(head.scale[4], 0.05)
        self.assertEqual(receipt["work"], fit_work(4, len(hidden), plan))
        self.assertEqual(receipt["accounting_units"], ledger.estimate_kernel(**receipt["work"]))
        self.assertEqual(receipt["accounting_units"], ledger.consumed_units)
        self.assertEqual(ledger.totals["critic_gain_head_fits"], 1)
        self.assertNotIn("model_forward_calls", ledger.totals)
        self.assertNotIn("optimizer_updates", ledger.totals)
        self.assertEqual(receipt["target"]["mean"], head.intercept)

    def test_fit_is_deterministic_and_seed_is_provenance_only(self):
        hidden, instruction, target, plan = self.fixture()
        first, _ = AffineGainHead.fit(hidden, instruction, target, plan, 11, WorkLedger("first"))
        second, receipt = AffineGainHead.fit(hidden, instruction, target, plan["controller"], 47, WorkLedger("second"))
        self.assertEqual(receipt["seed"], 47)
        for name in ARRAY_KEYS:
            np.testing.assert_array_equal(first.to_arrays()[name], second.to_arrays()[name])

    def test_ridge_admission_is_atomic_before_normalization_or_solve(self):
        hidden, instruction, target, plan = self.fixture()
        probe = WorkLedger("estimate")
        required = probe.estimate_kernel(**fit_work(4, len(hidden), plan))
        ledger = WorkLedger("too-small", total_cap=required - 1)
        with patch("independent.gain_head.np.linalg.solve", side_effect=AssertionError("unadmitted solve")):
            with self.assertRaises(BudgetExceeded):
                AffineGainHead.fit(hidden, instruction, target, plan, 11, ledger)
        self.assertEqual(ledger.consumed_units, 0)

    def test_npz_roundtrip_is_strict_immutable_and_supports_forced_laws(self):
        hidden, instruction, target, plan = self.fixture()
        head, _ = AffineGainHead.fit(hidden, instruction, target, plan, 11, WorkLedger("fixture"))
        arrays = head.to_arrays()
        self.assertEqual(set(arrays), ARRAY_KEYS)
        self.assertTrue(all(not value.flags.writeable for value in arrays.values()))
        stream = io.BytesIO()
        np.savez_compressed(stream, **arrays)
        stream.seek(0)
        with np.load(stream, allow_pickle=False) as encoded:
            restored = load_controller(encoded)
        np.testing.assert_array_equal(restored.predict_state(hidden, instruction), head.predict_state(hidden, instruction))
        for value in (restored.mean, restored.scale, restored.weights, restored.bounds):
            self.assertFalse(value.flags.writeable)
        np.testing.assert_array_equal(head.with_bounds([0.0, 0.0]).predict_state(hidden, instruction), np.zeros(len(hidden)))
        np.testing.assert_array_equal(head.with_bounds([1.0, 1.0]).predict_state(hidden, instruction), np.ones(len(hidden)))
        self.assertNotEqual(head.bounds.tolist(), [0.0, 0.0])
        with self.assertRaises(ValueError):
            head.weights[0] = 1.0

    def test_legacy_dispatch_and_malformed_headers(self):
        legacy = Controller(12, np.zeros(31), np.ones(31), np.zeros(31), 0.1, np.array([0.0, 1.0]))
        self.assertIsInstance(load_controller(legacy.to_arrays()), Controller)
        hidden, instruction, target, plan = self.fixture()
        head, _ = AffineGainHead.fit(hidden, instruction, target, plan, 11, WorkLedger("fixture"))
        arrays = head.to_arrays()
        for replacement in ({"gain_head_version": np.array([2], dtype=np.int64)},
                            {"gh_classes": np.array([13], dtype=np.int64)},
                            {"gh_hidden_dim": np.array([513], dtype=np.int64)},
                            {"gh_hidden_dim": np.array([4.0])},
                            {"gh_weights": np.zeros(14, dtype=np.float32)},
                            {"gh_scale": np.zeros(14)},
                            {"gh_bounds": np.array([1.0, -1.0])},
                            {"gh_intercept": np.array([np.nan])},
                            {"unknown": np.array([1])}):
            with self.subTest(replacement=tuple(replacement)):
                with self.assertRaises(ValueError):
                    load_controller({**arrays, **replacement})
        with self.assertRaises(ValueError):
            load_controller({})

    def test_public_inputs_and_work_geometry_reject_invalid_values(self):
        hidden, instruction, target, plan = self.fixture()
        head, _ = AffineGainHead.fit(hidden, instruction, target, plan, 11, WorkLedger("fixture"))
        for h, inst in ((hidden[:, :3], instruction), (hidden, instruction[:, :9]),
                        (hidden[:0], instruction[:0]), (hidden * np.nan, instruction)):
            with self.assertRaises(ValueError):
                head.predict_state(h, inst)
        for h, n in ((0, 1), (513, 1), (4, 0), (4, 65537), (True, 1)):
            with self.assertRaises(ValueError):
                head_work(h, n)
        with self.assertRaises(ValueError):
            AffineGainHead.fit(hidden, instruction, target * np.nan, plan, 11, WorkLedger("bad"))
        with self.assertRaises(ValueError):
            fit_work(4, 24, {"ridge_regularization": 0.0})
        quote = head_work(4, 3)
        self.assertEqual(quote, {"macs": 42, "scalar_ops": 45, "div_ops": 42, "compare_ops": 54})
        self.assertEqual(head.work(3), quote)
        self.assertNotIn("tanh_ops", quote)


if __name__ == "__main__":
    unittest.main()
