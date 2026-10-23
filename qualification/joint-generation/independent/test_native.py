"""Native equivalence and admission checks on random arrays, without datasets."""

import hashlib
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from control import Controller
from model import JointModel
from independent.accounting import BudgetExceeded, WorkLedger
from independent.inference import FrozenGenerator, units
from independent.native import NativeGenerator, SOURCE, compile_native


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.path = Path(cls.directory.name) / "kernel.so"
        cls.build = compile_native(cls.path)

    def setUp(self):
        self.model = JointModel(202, 12, 192, hidden=32, seed=29)
        self.x = np.random.default_rng(59).uniform(0, 1, size=(9, 202))

    def critic(self, gain=0.1):
        return Controller(12, np.zeros(31), np.ones(31), np.zeros(31), gain,
                          np.array([gain, gain]))

    def test_build_receipt_binds_uncached_compiler_source_and_library(self):
        self.assertEqual(self.build["exit_code"], 0)
        self.assertFalse(self.build["cached_compilation_used"])
        self.assertEqual(self.build["library_path"], str(self.path))
        self.assertEqual(self.build["source_sha256"], hashlib.sha256(SOURCE.read_bytes()).hexdigest())
        self.assertEqual(self.build["library_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertGreater(self.build["cpu_seconds"], 0)
        self.assertGreater(self.build["wall_seconds"], 0)
        self.assertIn("-O3", self.build["argv"])
        self.assertNotIn("-ffast-math", self.build["argv"])

    def test_full_low_and_declared_cost_match_python_without_weight_changes(self):
        before = self.model.digest()
        python_ledger, native_ledger = WorkLedger("python"), WorkLedger("native")
        python = FrozenGenerator(self.model, python_ledger)
        native = NativeGenerator(self.model, self.path, native_ledger)
        for method in ("forward_full", "forward_low"):
            expected = getattr(python, method)(self.x)
            actual = getattr(native, method)(self.x)
            for wanted, value in zip(expected, actual):
                np.testing.assert_allclose(value, wanted, rtol=1e-12, atol=1e-12)
        self.assertEqual(python_ledger.totals, native_ledger.totals)
        self.assertEqual(self.model.digest(), before)
        self.assertTrue(all(not value.flags.writeable for value in native.params.values()))
        self.model.params["encoder"][:] = 0
        for wanted, value in zip(python.forward_full(self.x), native.forward_full(self.x)):
            np.testing.assert_allclose(value, wanted, rtol=1e-12, atol=1e-12)

    def test_fused_critic_matches_root_prediction_for_nontrivial_parameters(self):
        rng = np.random.default_rng(82)
        critic = Controller(12, rng.normal(0, 0.1, 31), rng.uniform(0.1, 2, 31),
                            rng.normal(0, 0.03, 31), 0.1, np.array([-1.0, 1.0]))
        python, native = FrozenGenerator(self.model), NativeGenerator(self.model, self.path)
        for row in self.x:
            expected = python.forward_low(row[None, :])
            p, q, gain = native._call_low_critic(row[None, :], native._critic(critic))
            for wanted, value in zip(expected, (p, q)):
                np.testing.assert_allclose(value, wanted, rtol=1e-12, atol=1e-12)
            np.testing.assert_allclose(gain, critic.predict_gain(*expected)[0], rtol=1e-12, atol=1e-12)

    def test_actions_outputs_and_costs_match_for_stop_continue_and_tie(self):
        for gain, continued in ((-0.1, False), (0.02, False), (0.2, True)):
            python_ledger, native_ledger = WorkLedger("python"), WorkLedger("native")
            python = FrozenGenerator(self.model, python_ledger)
            native = NativeGenerator(self.model, self.path, native_ledger)
            expected = python.continuation(self.x[:1], self.critic(gain))
            actual = native.continuation(self.x[:1], self.critic(gain))
            self.assertEqual(actual[2], expected[2])
            self.assertEqual(actual[2]["continued"], continued)
            for wanted, value in zip(expected[:2], actual[:2]):
                np.testing.assert_allclose(value, wanted, rtol=1e-12, atol=1e-12)
            self.assertEqual(python_ledger.totals, native_ledger.totals)

    def test_short_optional_budget_never_executes_or_charges_full(self):
        native = NativeGenerator(self.model, self.path)
        required = units(native.low_work(1)) + units(native.critic_work(1))
        ledger = WorkLedger("stop", required)
        with patch.object(native, "forward_full", side_effect=AssertionError("unfunded full")):
            _, _, receipt = native.continuation(self.x[:1], self.critic(), ledger=ledger)
        self.assertFalse(receipt["continued"])
        self.assertEqual(ledger.consumed_units, required)
        self.assertEqual(ledger.totals["model_forward_rows"], 1)

    def test_unfunded_mandatory_work_is_rejected_before_c_call_or_prepare(self):
        native = NativeGenerator(self.model, self.path, prepare_low=False)
        required = units(native.low_work(1)) + units(native.critic_work(1)) + units(native.prepare_work())
        ledger = WorkLedger("reject", required - 1)
        with patch.object(native, "_call_low_critic", side_effect=AssertionError("unfunded C call")):
            with self.assertRaises(BudgetExceeded):
                native.continuation(self.x[:1], self.critic(), ledger=ledger)
        self.assertEqual(ledger.consumed_units, 0)
        self.assertFalse(native.prepared_low)
        full_ledger = WorkLedger("full", units(native.full_work(1)) - 1)
        with patch.object(native, "_call_forward", side_effect=AssertionError("unfunded full C call")):
            with self.assertRaises(BudgetExceeded):
                native.forward_full(self.x[:1], full_ledger)

    def test_bad_inputs_models_and_critics_reject_in_python(self):
        native = NativeGenerator(self.model, self.path)
        invalids = (self.x.astype(np.float32), self.x.astype(np.int64), np.zeros((1, 58)),
                    np.zeros((0, 202)), np.full((1, 202), np.nan),
                    np.full((1, 202), 1.01), np.full((1, 202), -0.01))
        for value in invalids:
            with patch.object(native, "_call_forward", side_effect=AssertionError("invalid input reached C")):
                with self.assertRaises(ValueError):
                    native.forward_low(value)
        self.model.params["encoder"][0, 0] = np.nan
        with self.assertRaises(ValueError):
            NativeGenerator(self.model, self.path)
        bad = self.critic()
        object.__setattr__(bad, "scale", np.zeros(31))
        with patch.object(native, "_call_low_critic", side_effect=AssertionError("invalid critic reached C")):
            with self.assertRaises(ValueError):
                native.continuation(self.x[:1], bad)

    def test_full_only_avoids_unexecuted_fold_and_critic(self):
        ledger = WorkLedger("full")
        native = NativeGenerator(self.model, self.path, ledger, prepare_low=False)
        native.forward_full(self.x)
        self.assertEqual(ledger.consumed_units, units(native.full_work(9)))
        self.assertFalse(native.prepared_low)
        self.assertNotIn("critic_decisions", ledger.totals)

    def test_batch_64_matches_individual_outputs_actions_and_actual_cost(self):
        x = np.random.default_rng(89).uniform(0, 1, (64, 202))
        mask = np.arange(64) % 2 == 0
        for mode, gain in (("full", .1), ("low", .1), ("ensemble", .1),
                           ("continuation", .1), ("continuation", -.1), ("random", .1)):
            native, single = NativeGenerator(self.model, self.path), NativeGenerator(self.model, self.path)
            ledger, reference = WorkLedger("batch"), WorkLedger("individual")
            p, q, receipt = native.batch(x, mode, self.critic(gain), ledger=ledger,
                                        random_full_mask=mask if mode == "random" else None)
            ps, qs, costs = [], [], []
            for index, row in enumerate(x):
                before = reference.consumed_units
                if mode == "continuation":
                    a, b, action = single.continuation(row[None], self.critic(gain), ledger=reference)
                    self.assertEqual(receipt["continued"][index], action["continued"])
                elif mode == "ensemble":
                    pl, ql = single.forward_low(row[None], reference)
                    pf, qf = single.forward_full(row[None], reference)
                    reference.charge_kernel("inference", "two_view_average", scalar_ops=24, div_ops=24)
                    a, b = (pl + pf) / 2, (ql + qf) / 2
                else:
                    selected = mode if mode != "random" else "full" if mask[index] else "low"
                    if mode == "random":
                        reference.charge_kernel("inference", "random_view_choice", scalar_ops=1, compare_ops=1)
                    a, b = getattr(single, "forward_" + selected)(row[None], reference)
                ps.append(a[0]); qs.append(b[0]); costs.append(reference.consumed_units - before)
            np.testing.assert_allclose(p, ps, rtol=1e-12, atol=1e-12)
            np.testing.assert_allclose(q, qs, rtol=1e-12, atol=1e-12)
            self.assertEqual(receipt["per_row_work_units"], costs)
            self.assertEqual(ledger.consumed_units, reference.consumed_units)
            self.assertEqual(sum(receipt["per_row_work_units"]), receipt["actual_units"])
            self.assertFalse(receipt["reservation_charged"])

    def test_batch_reserves_worst_case_but_never_charges_unexecuted_full_or_critic(self):
        native = NativeGenerator(self.model, self.path)
        mandatory = units(native.low_work(1)) + units(native.critic_work(1))
        worst = mandatory + units(native.full_work(1))
        ledger = WorkLedger("short", 9 * worst - 1)
        with patch.object(native, "_call_batch", side_effect=AssertionError("unfunded batch")):
            with self.assertRaises(BudgetExceeded):
                native.batch(self.x, "continuation", self.critic(-.1), ledger=ledger)
            with self.assertRaises(BudgetExceeded):
                native.batch(self.x, "continuation", self.critic(-.1), per_request_cap=worst - 1)
        self.assertEqual(ledger.consumed_units, 0)
        ledger = WorkLedger("funded", 9 * worst)
        _, _, receipt = native.batch(self.x, "continuation", self.critic(-.1), ledger=ledger)
        self.assertEqual(ledger.consumed_units, 9 * mandatory)
        self.assertEqual(receipt["per_row"]["full_forwards"], [0] * 9)
        native = NativeGenerator(self.model, self.path, prepare_low=False)
        with patch.object(native, "_critic", side_effect=AssertionError("unused random critic")):
            _, _, receipt = native.batch(self.x, "random", object(), random_full_mask=np.ones(9, dtype=bool))
        self.assertFalse(native.prepared_low)
        self.assertEqual(receipt["actual_units"], 9 * (units(native.full_work(1)) + 2))


if __name__ == "__main__":
    unittest.main()
