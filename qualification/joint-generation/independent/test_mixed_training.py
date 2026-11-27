"""Bounded hand-array proofs; no experiment data or qualification execution."""

import copy
import unittest
from unittest.mock import patch

import numpy as np

from independent.accounting import BudgetExceeded, WorkLedger
from independent.learning import CachedObjective, CONTENT_PARAMETERS, step_work
from independent.mixed_training import MixedEncoderBatch, mixed_step_work
from model import JointModel, softmax


def fixture(n, mask):
    rng = np.random.default_rng(9200 + n)
    full = rng.uniform(-0.6, 0.6, (n, 202))
    anchors = rng.uniform(-0.6, 0.6, (n, 4, 4, 3))
    low = np.concatenate((anchors.repeat(2, 1).repeat(2, 2).reshape(n, 192),
                          full[:, 192:]), axis=1)
    return np.where(mask[:, None], full, low), rng.integers(12, size=n)


class MixedTrainingTests(unittest.TestCase):
    def assert_model(self, actual, expected, *, steps=0, bitwise=False):
        self.assertEqual(actual.updates, expected.updates)
        self.assertEqual(set(actual._moments), set(expected._moments))
        for key in actual.params:
            if bitwise or key.startswith("decoder"):
                np.testing.assert_array_equal(actual.params[key], expected.params[key])
            else:
                tolerance = 2e-8 if steps == 1 else 2e-7
                np.testing.assert_allclose(actual.params[key], expected.params[key],
                                           rtol=tolerance, atol=tolerance)
        for key, (m, v, clock) in actual._moments.items():
            em, ev, expected_clock = expected._moments[key]
            self.assertEqual(clock, expected_clock)
            for left, right in ((m, em), (v, ev)):
                if bitwise or key.startswith("decoder"):
                    np.testing.assert_array_equal(left, right)
                else:
                    np.testing.assert_allclose(left, right, rtol=2e-10, atol=2e-12)

    def test_encoder_forward_pullback_all_geometries_and_fresh_fold(self):
        for n, h, mask in ((1, 1, np.zeros(1, bool)),
                           (5, 4, np.ones(5, bool)),
                           (5, 4, np.array([True, False, True, True, True])),
                           (5, 4, np.array([False, True, False, True, False])),
                           (64, 32, np.arange(64) % 3 == 0)):
            with self.subTest(n=n, h=h, low=int((~mask).sum())):
                x, _ = fixture(n, mask)
                model = JointModel(202, 12, 192, hidden=h, seed=31)
                batch = MixedEncoderBatch(x, mask)
                self.assertEqual((batch.full_count, batch.low_count),
                                 (int(mask.sum()), int((~mask).sum())))
                dh = np.random.default_rng(n + h).normal(size=(n, h))
                for increment in (0.0, 0.013):
                    model.params["encoder"] += increment
                    dense = x @ model.params["encoder"] + model.params["bias"]
                    hidden = batch.hidden(model.params["encoder"], model.params["bias"])
                    np.testing.assert_allclose(batch.preactivation(model.params["encoder"],
                        model.params["bias"]), dense, rtol=2e-12, atol=4e-12)
                    np.testing.assert_allclose(hidden, np.tanh(dense), rtol=2e-12, atol=4e-12)
                    for head in ("text", "image"):
                        np.testing.assert_allclose(softmax(hidden @ model.params[head]),
                            softmax(np.tanh(dense) @ model.params[head]), rtol=2e-12, atol=4e-12)
                    np.testing.assert_allclose(batch.encoder_gradient(dh), x.T @ dh,
                                               rtol=2e-11, atol=2e-12)

    def compare_steps(self, arm, steps, mask, *, multiplier=1.0, bitwise=False):
        x, y = fixture(len(mask), mask)
        actual = JointModel(202, 12, 192, hidden=4, seed=43)
        actual.apply_gradients({"decoder": np.full((12, 192), 0.01),
                                "decoder_bias": np.full(192, -0.01)}, 0.001)
        expected = copy.deepcopy(actual)
        mixed, dense = CachedObjective(arm, actual), CachedObjective(arm, expected)
        for _ in range(steps):
            captured = {}
            def run(model, objective, name, full_mask):
                original = model.apply_gradients
                def apply(grads, lr):
                    captured[name] = {key: value.copy() for key, value in grads.items()}
                    original({key: value * multiplier for key, value in grads.items()}, lr)
                with patch.object(model, "apply_gradients", side_effect=apply):
                    return objective.step(model, x, y, 0.003, full_mask=full_mask)
            left, right = run(actual, mixed, "mixed", mask), run(expected, dense, "dense", None)
            np.testing.assert_allclose(left, right, rtol=2e-12, atol=4e-12)
            self.assertEqual(set(captured["mixed"]), set(CONTENT_PARAMETERS))
            for key in CONTENT_PARAMETERS:
                if bitwise:
                    np.testing.assert_array_equal(captured["mixed"][key], captured["dense"][key])
                else:
                    np.testing.assert_allclose(captured["mixed"][key], captured["dense"][key],
                                               rtol=2e-11, atol=2e-12)
            self.assert_model(actual, expected, steps=steps, bitwise=bitwise)
        return np.sqrt(sum(float(np.sum(g * g)) for g in captured["dense"].values())) * multiplier

    def test_four_objectives_one_and_eight_updates_and_all_full_bitwise(self):
        for arm in ("S", "H", "A", "N"):
            with self.subTest(arm=arm):
                self.compare_steps(arm, 1, np.array([False, True, False, True, False]))
                self.compare_steps(arm, 8, np.array([True, False, True, False, False]))
                self.compare_steps(arm, 2, np.ones(5, bool), bitwise=True)

    def test_optimizer_clipping_sides_and_boundary_use_same_pullback(self):
        mask = np.array([False, True, False, True, False])
        norm = self.compare_steps("S", 1, mask)
        for desired in (0.25, 5.0, 20.0):
            with self.subTest(desired_norm=desired):
                measured = self.compare_steps("S", 1, mask, multiplier=desired / norm)
                self.assertAlmostEqual(measured, desired, places=12)

    def test_inventory_exact_counts_and_componentwise_reservation(self):
        dims, n = (202, 12, 192, 4), 5
        for arm in ("S", "H", "A", "N"):
            bound = mixed_step_work(dims, arm, n)
            dense = step_work(dims, arm, n)
            for low in range(n + 1):
                with self.subTest(arm=arm, low=low):
                    mask = np.arange(n) >= low
                    x, y = fixture(n, mask)
                    model, ledger = JointModel(202, 12, 192, hidden=4, seed=43), WorkLedger(arm)
                    quote = mixed_step_work(dims, arm, n, low)
                    for key, value in quote.items():
                        self.assertLessEqual(value, bound[key])
                    self.assertEqual(quote["macs"], dense["macs"] - 288 * 4 * low)
                    self.assertEqual(quote["scalar_ops"], dense["scalar_ops"] + n
                                     + 144 * 4 * bool(low) + 202 * 4 * (0 < low < n))
                    self.assertEqual(quote["compare_ops"], dense["compare_ops"] + 2 * n + 144 * low)
                    CachedObjective(arm, model).step(model, x, y, .003, ledger=ledger, full_mask=mask)
                    totals = ledger.totals
                    self.assertEqual(ledger.consumed_units, ledger.estimate_kernel(**quote))
                    for key, value in quote.items():
                        self.assertEqual(totals["op_" + key], value)
                    self.assertEqual(totals["encoder_full_rows"], n - low)
                    self.assertEqual(totals["encoder_low_rows"], low)
                    self.assertEqual(totals["encoder_fold_builds"], int(low > 0))
                    self.assertEqual(totals["encoder_gradient_merges"], int(0 < low < n))
                    self.assertEqual(totals["model_forward_macs"], n * (202 * 4 + 2 * 4 * 12) - 144 * 4 * low)
                    self.assertEqual(totals["model_backward_macs"], n * (202 * 4 + 4 * 4 * 12) - 144 * 4 * low)
                    for key in ("content_updates", "optimizer_updates", "model_forward_calls", "model_backward_calls"):
                        self.assertEqual(totals[key], 1)
                    self.assertEqual(totals["training_examples"], n)
            custom = WorkLedger("prices", prices={key: index + 1 for index, key in enumerate(WorkLedger("p").prices)})
            for low in range(n + 1):
                self.assertLessEqual(custom.estimate_kernel(**mixed_step_work(dims, arm, n, low)),
                                     custom.estimate_kernel(**bound))
        for n in (1, 64):
            bound = mixed_step_work((202, 12, 192, 32), "N", n)
            for low in range(n + 1):
                for key, value in mixed_step_work((202, 12, 192, 32), "N", n, low).items():
                    self.assertLessEqual(value, bound[key])

    def test_bad_masks_low_blocks_and_insufficient_cap_are_atomic(self):
        mask = np.array([False, True, False, True, False])
        x, y = fixture(5, mask)
        model = JointModel(202, 12, 192, hidden=4, seed=43)
        objective = CachedObjective("N", model)
        corrupt = x.copy()
        corrupt[0, 3] += 0.1
        invalid = ((x, mask.astype(int)), (x, mask[:, None]), (x, mask[:-1]),
                   (corrupt, mask), (x, np.zeros(5, bool)))
        for inputs, full in invalid:
            with self.subTest(mask_shape=np.asarray(full).shape):
                before, ledger = copy.deepcopy(model), WorkLedger("invalid")
                receipt = ledger.snapshot()
                with self.assertRaises(ValueError):
                    objective.step(model, inputs, y, .003, ledger=ledger, full_mask=full)
                self.assertEqual(ledger.snapshot(), receipt)
                self.assert_model(model, before, bitwise=True)
        quote = mixed_step_work(model.dimensions, "N", 5, 3)
        probe = WorkLedger("probe")
        ledger = WorkLedger("short", total_cap=probe.estimate_kernel(**quote) - 1)
        before, receipt = copy.deepcopy(model), ledger.snapshot()
        with patch.object(MixedEncoderBatch, "hidden", side_effect=AssertionError("math before admission")):
            with self.assertRaises(BudgetExceeded):
                objective.step(model, x, y, .003, ledger=ledger, full_mask=mask)
        self.assertEqual(ledger.snapshot(), receipt)
        self.assert_model(model, before, bitwise=True)
        for low in (-1, 6, True, 2.0):
            with self.assertRaises(ValueError):
                mixed_step_work(model.dimensions, "N", 5, low)


if __name__ == "__main__":
    unittest.main()
