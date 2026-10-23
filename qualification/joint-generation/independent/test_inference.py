"""Small synthetic-array inference checks; no experimental dataset is opened."""

import unittest
from unittest.mock import patch

import numpy as np

from control import Controller
from model import JointModel, softmax
from independent.accounting import BudgetExceeded, WorkLedger
from independent.inference import FrozenGenerator, units


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.model = JointModel(202, 12, 192, hidden=32, seed=19)
        self.x = np.random.default_rng(83).uniform(0, 1, size=(7, 202))

    def critic(self, gain=1.0):
        return Controller(12, np.zeros(31), np.ones(31), np.zeros(31), gain,
                          np.array([gain, gain]))

    def test_folded_low_matches_original_upsampled_logits_and_probabilities(self):
        images = self.x[:, :192].reshape(7, 4, 2, 4, 2, 3)
        thumbnail = images.mean(axis=(2, 4)).repeat(2, axis=1).repeat(2, axis=2)
        original_low = np.concatenate((thumbnail.reshape(7, 192), self.x[:, 192:]), axis=1)
        hidden = np.tanh(original_low @ self.model.params["encoder"] + self.model.params["bias"])
        expected_logits = [hidden @ self.model.params[name] + self.model.params[name + "_bias"]
                           for name in ("text", "image")]
        expected = self.model.forward(original_low)
        generator = FrozenGenerator(self.model)
        with patch("independent.inference.softmax", wraps=softmax) as observed:
            actual = generator.forward_low(self.x)
        for wanted, call in zip(expected_logits, observed.call_args_list):
            np.testing.assert_allclose(call.args[0], wanted, rtol=1e-12, atol=1e-12)
        for wanted, value in zip(expected, actual):
            np.testing.assert_allclose(value, wanted, rtol=1e-12, atol=1e-12)

    def test_full_matches_original_and_snapshot_never_changes_source_weights(self):
        before = self.model.digest()
        generator = FrozenGenerator(self.model)
        expected = self.model.forward(self.x)
        for wanted, value in zip(expected, generator.forward_full(self.x)):
            np.testing.assert_array_equal(value, wanted)
        generator.forward_low(self.x)
        self.assertEqual(self.model.digest(), before)
        self.assertTrue(all(not value.flags.writeable for value in generator.params.values()))
        self.model.params["encoder"][:] = 0
        for wanted, value in zip(expected, generator.forward_full(self.x)):
            np.testing.assert_array_equal(value, wanted)

    def test_low_executes_only_58_input_multiply_and_real_reduced_work(self):
        ledger = WorkLedger("low")
        generator = FrozenGenerator(self.model, ledger)
        prepared = ledger.consumed_units
        self.assertGreater(prepared, 0)
        self.assertEqual(prepared, units(generator.prepare_work(), ledger))
        with patch.object(self.model, "forward", side_effect=AssertionError("unbilled root pass")):
            with patch.object(generator, "_content", wraps=generator._content) as execute:
                generator.forward_low(self.x)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(execute.call_args.args[0].shape, (7, 58))
        self.assertEqual(execute.call_args.args[1].shape, (58, 32))
        self.assertEqual(ledger.consumed_units - prepared, units(generator.low_work(7), ledger))
        self.assertLess(units(generator.low_work(7)), units(generator.full_work(7)))
        self.assertEqual(ledger.totals["model_forward_macs"], 7 * (58 * 32 + 2 * 32 * 12))
        generator.forward_low(self.x[:1])
        self.assertEqual(ledger.snapshot()["kernels"]["prepare"]["thumbnail_encoder_fold"]["calls"], 1)

    def test_full_only_does_not_fold_or_call_critic(self):
        ledger = WorkLedger("full")
        generator = FrozenGenerator(self.model, ledger, prepare_low=False)
        self.assertEqual(ledger.consumed_units, 0)
        generator.forward_full(self.x)
        self.assertFalse(generator.prepared_low)
        self.assertEqual(ledger.consumed_units, units(generator.full_work(7), ledger))
        self.assertNotIn("prepare", ledger.snapshot()["kernels"])
        self.assertNotIn("critic_decisions", ledger.totals)

    def test_rejects_before_any_unfunded_full_or_low_computation(self):
        generator = FrozenGenerator(self.model, prepare_low=False)
        for method, work in ((generator.forward_full, generator.full_work(1)),
                             (generator.forward_low,
                              {key: generator.low_work(1).get(key, 0) + generator.prepare_work().get(key, 0)
                               for key in set(generator.low_work(1)) | set(generator.prepare_work())})):
            ledger = WorkLedger("reject", total_cap=units(work) - 1)
            with patch.object(generator, "_content", wraps=generator._content) as execute:
                with self.assertRaises(BudgetExceeded):
                    method(self.x[:1], ledger)
            self.assertEqual(execute.call_count, 0)
            self.assertEqual(ledger.consumed_units, 0)
        self.assertFalse(generator.prepared_low)

    def test_continuation_precharges_every_real_kernel_and_never_exceeds_two_passes(self):
        generator = FrozenGenerator(self.model)
        mandatory = units(generator.low_work(1)) + units(generator.critic_work(1))
        full = units(generator.full_work(1))
        ledger = WorkLedger("continue", total_cap=mandatory + full)
        p, q, receipt = generator.continuation(self.x[:1], self.critic(), ledger=ledger)
        self.assertEqual(receipt["model_forwards"], 2)
        self.assertTrue(receipt["continued"])
        self.assertEqual(ledger.consumed_units, mandatory + full)
        self.assertEqual(ledger.totals["model_forward_rows"], 2)
        for wanted, value in zip(generator.forward_full(self.x[:1]), (p, q)):
            np.testing.assert_array_equal(value, wanted)

    def test_optional_full_pass_is_disabled_instead_of_unbilled_when_cap_is_short(self):
        generator = FrozenGenerator(self.model)
        mandatory = units(generator.low_work(1)) + units(generator.critic_work(1))
        ledger = WorkLedger("stop", total_cap=mandatory)
        with patch.object(generator, "forward_full", side_effect=AssertionError("unfunded full pass")):
            _, _, receipt = generator.continuation(self.x[:1], self.critic(), ledger=ledger)
        self.assertFalse(receipt["continued"])
        self.assertEqual(receipt["model_forwards"], 1)
        self.assertEqual(ledger.consumed_units, mandatory)
        self.assertEqual(ledger.totals["model_forward_rows"], 1)

    def test_mandatory_low_and_critic_reject_atomically_and_negative_gain_stops(self):
        generator = FrozenGenerator(self.model)
        mandatory = units(generator.low_work(1)) + units(generator.critic_work(1))
        ledger = WorkLedger("mandatory", total_cap=mandatory - 1)
        with patch.object(generator, "forward_low", side_effect=AssertionError("unfunded mandatory work")):
            with self.assertRaises(BudgetExceeded):
                generator.continuation(self.x[:1], self.critic(), ledger=ledger)
        self.assertEqual(ledger.consumed_units, 0)
        ledger = WorkLedger("negative")
        _, _, receipt = generator.continuation(self.x[:1], self.critic(-0.1), ledger=ledger)
        self.assertEqual(receipt["model_forwards"], 1)
        self.assertFalse(receipt["continued"])

    def test_custom_price_table_and_input_boundaries(self):
        generator = FrozenGenerator(self.model)
        prices = dict(WorkLedger("default").prices)
        prices["macs"] = 5
        ledger = WorkLedger("custom", prices=prices)
        generator.forward_low(self.x[:1], ledger)
        self.assertEqual(ledger.consumed_units, units(generator.low_work(1), ledger))
        self.assertGreater(units(generator.low_work(1), ledger), units(generator.low_work(1)))
        for invalid in (np.zeros((1, 58)), np.zeros((0, 202)), np.full((1, 202), np.nan)):
            with self.assertRaises(ValueError):
                generator.forward_low(invalid)
        with self.assertRaises(ValueError):
            generator.continuation(self.x, self.critic())
        with self.assertRaises(TypeError):
            generator.continuation(self.x[:1], self.critic(), labels=[0])


if __name__ == "__main__":
    unittest.main()
