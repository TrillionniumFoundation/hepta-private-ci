"""Manual tensors and mocked clocks; one real-C output check, no dataset API."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from control import fit_controller
from independent import controller_cost as c
from independent.accounting import BudgetExceeded, WorkLedger
from independent.inference import FrozenGenerator, _sum_work
from independent.native import compile_native
from model import JointModel


class ControllerCostTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(56019)
        self.model = JointModel(202, 12, 192, hidden=4, seed=19)
        full = rng.random((2, 202))
        self.data = {"split": "train", "full": full, "labels": np.array([0, 1]),
            "source_scenes": np.array([0, 1]), "source_ids": ["manual-a", "manual-b"],
            "input_hashes": [hashlib.sha256(row.astype("<f8").tobytes()).hexdigest() for row in full]}
        self.plan = {"model_seeds": [11, 23, 47], "compute_price": 0.02,
            "calibration_rows": 2, "calibration_repeats": 3,
            "controller": {"ridge_regularization": 0.001}}
        self.runtime = {**self.plan, "runtime_batch_size": 64, "runtime_backend": "python"}
        self.reward = rng.uniform(-0.35, 1, (12, 12, 12))

    def fake_measure(self, deltas=(40, 80, 60), calls=None, mutate=False):
        def measured(model, critic, mode, data, plan, reference, *, seed, observe):
            self.assertEqual((mode, observe, plan["compute_price"], plan["decision_price"]),
                             ("continuation", False, 0.02, 0.5))
            go = int(critic.bounds[0])
            np.testing.assert_array_equal(critic.bounds, [go, go])
            if calls is not None:
                calls.append((go, seed, critic))
            repeat = (seed - (23 if seed % 1009 == 23 else 11)) // 1009
            gen = FrozenGenerator(model, prepare_low=False)
            n = len(data["full"])
            prep, ledger = WorkLedger("prepare"), WorkLedger("probe")
            prep.charge_kernel("prepare", "fold", **gen.prepare_work())
            prediction = critic.work(n) if getattr(critic, "kind", None) == c.AFFINE_KIND else gen.critic_work(n)
            work = _sum_work(gen.low_work(n), prediction, gen.full_work(n) if go else {},
                            {key: n * value for key, value in c.output_work().items()})
            ledger.charge_kernel("inference", "fixture", **work)
            ledger.decoder("output", rows=n, pixels=192)
            ledger.record("output", output_bytes=100 * n, serialized_requests=n)
            cpu = 100 + go * deltas[repeat]
            if mutate:
                model.params["bias"][0] += 0.01
            return {"budget_violations": 0, "model_forwards": n * (1 + go),
                "per_row_cost": {"work_units": [ledger.consumed_units // n] * n},
                "cost": {"prepare": prep.snapshot(), "operator_totals": ledger.totals,
                    "batches": [{"rows": n, "cpu_ns": cpu, "wall_ns": cpu + 1}],
                    "runtime_batch_size": 64, "cpu_ns": cpu, "wall_ns": cpu + 1,
                    "prepare_cpu_ns": 10, "prepare_wall_ns": 11, "request_cap_units": 100000}}
        return measured

    def call(self, *, seed=11, reward=True, ledger=None):
        return c.fit_and_calibrate(self.model, self.data, self.data, self.plan, self.runtime,
            WorkLedger("NC") if ledger is None else ledger, 100.0, seed,
            raw_reward=self.reward if reward else None)

    def test_raw_targets_pair_order_coefficients_and_cost_conservation(self):
        calls, ledger = [], WorkLedger("NC")
        before = self.model.digest()
        gen = FrozenGenerator(self.model)
        pl, ql = gen.forward_low(self.data["full"])
        pf, qf = gen.forward_full(self.data["full"])
        y = self.data["labels"]
        expected = np.einsum("ni,nij,nj->n", pf, self.reward[y], qf) - np.einsum("ni,nij,nj->n", pl, self.reward[y], ql)
        with patch.object(c, "measure", self.fake_measure(calls=calls)), patch.object(c, "fit_controller", wraps=fit_controller) as fit:
            critic, decision, receipt = self.call(ledger=ledger)
        np.testing.assert_allclose(fit.call_args.args[2], expected, rtol=0, atol=1e-14)
        self.assertEqual([(go, seed) for go, seed, _ in calls], [(0, 11), (1, 11), (1, 1020), (0, 1020), (0, 2029), (1, 2029)])
        for _, _, forced in calls:
            for name in ("mean", "scale", "weights", "intercept"):
                np.testing.assert_array_equal(getattr(forced, name), getattr(critic, name))
            self.assertFalse(forced.mean.flags.writeable)
        self.assertEqual(receipt["paired_cpu_deltas_ns_per_request"], [20.0, 40.0, 30.0])
        self.assertEqual((receipt["cost_ratio"], decision), (0.3, 0.006))
        self.assertEqual(before, self.model.digest())
        expected_units = ledger.estimate_kernel(**c.controller_work(self.model, 2, 2, 3))
        self.assertEqual(receipt["accounting_units"], expected_units)
        self.assertEqual(ledger.consumed_units, expected_units)
        self.assertEqual(set(ledger.snapshot()["stages"]), {"critic_targets", "critic_fit", "controller_calibration"})
        self.assertLess(len(json.dumps(receipt)), 128 * 1024)

    def test_negative_median_is_retained_and_clamped_only_for_decision(self):
        calls = []
        with patch.object(c, "measure", self.fake_measure(deltas=(-20, -40, 10), calls=calls)):
            _, decision, receipt = self.call(seed=23)
        self.assertEqual(receipt["paired_cpu_deltas_ns_per_request"], [-10.0, -20.0, 5.0])
        self.assertEqual(receipt["median_incremental_cpu_ns_per_request"], -10.0)
        self.assertEqual((decision, receipt["cost_ratio"]), (0.0, 0.0))
        self.assertEqual([go for go, _, _ in calls], [1, 0, 0, 1, 1, 0])

    def test_uncached_reward_observation_is_paid_once_without_entropic_work(self):
        ledger = WorkLedger("NC")
        with patch.object(c, "measure", self.fake_measure()):
            self.call(reward=False, ledger=ledger)
        self.assertEqual(ledger.totals["objective_cache_builds"], 1)
        self.assertEqual(ledger.totals.get("entropic_gradient_calls", 0), 0)
        self.assertEqual(ledger.consumed_units,
            ledger.estimate_kernel(**c.controller_work(self.model, 2, 2, 3, raw_reward_cached=False)))

    def test_low_and_full_targets_reuse_the_same_label_indexed_reward_tensor(self):
        with patch.object(c, "measure", self.fake_measure()), \
             patch.object(c.np, "einsum", wraps=np.einsum) as contract:
            self.call()
        rewards = [call.args[1] for call in contract.call_args_list
                   if call.args[0] == "nij,nj->ni"]
        self.assertEqual(len(rewards), 2)
        self.assertIs(rewards[0], rewards[1])
        np.testing.assert_array_equal(rewards[0], self.reward[self.data["labels"]])

    def test_budget_rejects_before_forward_or_probe(self):
        ledger = WorkLedger("NC", total_cap=1)
        with patch.object(c, "measure", side_effect=AssertionError("probe must not run")), patch.object(FrozenGenerator, "forward_low", side_effect=AssertionError("forward must not run")):
            with self.assertRaises(BudgetExceeded):
                self.call(ledger=ledger)
        self.assertEqual(ledger.consumed_units, 0)

    def test_wrong_split_hash_and_mutation_are_rejected(self):
        for change in ({"split": "test"}, {"input_hashes": ["0" * 64, "1" * 64]}):
            altered = {**self.data, **change}
            with self.assertRaises(ValueError):
                c.fit_and_calibrate(self.model, self.data, altered, self.plan, self.runtime,
                                    WorkLedger("NC"), 100.0, 11, self.reward)
        with patch.object(c, "measure", self.fake_measure(mutate=True)):
            with self.assertRaisesRegex(ValueError, "changed content"):
                self.call()

    def test_real_c_probes_generate_complete_outputs_and_exact_forced_routes(self):
        with tempfile.TemporaryDirectory() as root:
            library = Path(root) / "joint.so"
            compile_native(library)
            self.runtime.update(runtime_backend="native", native_library=str(library))
            for kind in ("probability-ridge-v1", c.AFFINE_KIND):
                with self.subTest(kind=kind):
                    self.plan["controller"]["gain_head"] = kind
                    ledger = WorkLedger("NC")
                    _, _, receipt = self.call(ledger=ledger)
                    self.assertEqual(receipt["critic_kind"], kind)
                    for pair in receipt["pairs"]:
                        self.assertEqual([pair[name]["model_forwards"] for name in ("stop", "continue")], [2, 4])
                        for name in ("stop", "continue"):
                            self.assertGreater(pair[name]["cost"]["operator_totals"]["output_bytes"], 0)
                            self.assertEqual(pair[name]["cost"]["operator_totals"]["serialized_requests"], 2)
                    self.assertEqual(ledger.consumed_units, ledger.estimate_kernel(
                        **c.controller_work(self.model, 2, 2, 3, plan=self.plan)))

    def test_affine_reuses_one_low_state_and_prices_fit_and_forced_pairs(self):
        from independent.gain_head import AffineGainHead, fit_work
        self.plan["controller"]["gain_head"] = c.AFFINE_KIND
        ledger, calls, low_rows, full_rows = WorkLedger("affine-NC"), [], [], []
        low_state, full_forward = FrozenGenerator.forward_low_state, FrozenGenerator.forward_full

        def record_low(generator, x, *args, **kwargs):
            low_rows.append(len(x))
            return low_state(generator, x, *args, **kwargs)

        def record_full(generator, x, *args, **kwargs):
            full_rows.append(len(x))
            return full_forward(generator, x, *args, **kwargs)

        before = self.model.digest()
        with patch.object(c, "measure", self.fake_measure(calls=calls)), \
             patch.object(c, "fit_controller", side_effect=AssertionError("unused probability ridge")), \
             patch.object(FrozenGenerator, "forward_low_state", record_low), \
             patch.object(FrozenGenerator, "forward_full", record_full), \
             patch.object(AffineGainHead, "fit", wraps=AffineGainHead.fit) as fit:
            critic, decision, receipt = self.call(ledger=ledger)
        self.assertEqual((low_rows, full_rows), ([2], [2]))
        self.assertIsInstance(critic, AffineGainHead)
        self.assertEqual(receipt["critic_kind"], c.AFFINE_KIND)
        self.assertEqual(receipt["gain_head_fit"]["input_dim"], self.model.dimensions[3] + 10)
        self.assertEqual(receipt["gain_head_fit"]["accounting_units"],
                         ledger.estimate_kernel(**fit_work(self.model.dimensions[3], 2, self.plan)))
        h, instruction, target = fit.call_args.args[:3]
        np.testing.assert_array_equal(instruction, self.data["full"][:, 192:])
        reference = FrozenGenerator(self.model)
        pl, ql = reference.forward_low(self.data["full"])
        pf, qf = reference.forward_full(self.data["full"])
        y = self.data["labels"]
        expected = np.einsum("ni,nij,nj->n", pf, self.reward[y], qf) - np.einsum("ni,nij,nj->n", pl, self.reward[y], ql)
        np.testing.assert_allclose(target, expected, rtol=0, atol=1e-14)
        self.assertEqual(h.shape, (2, self.model.dimensions[3]))
        for _, _, forced in calls:
            self.assertIsInstance(forced, AffineGainHead)
            for name in ("mean", "scale", "weights", "intercept"):
                np.testing.assert_array_equal(getattr(forced, name), getattr(critic, name))
        self.assertEqual((receipt["cost_ratio"], decision), (0.3, 0.006))
        self.assertEqual(self.model.digest(), before)
        self.assertEqual(ledger.consumed_units, ledger.estimate_kernel(
            **c.controller_work(self.model, 2, 2, 3, plan=self.plan)))

    def test_affine_budget_reserves_entire_fit_and_probes_before_any_forward(self):
        self.plan["controller"]["gain_head"] = c.AFFINE_KIND
        total = WorkLedger("price").estimate_kernel(**c.controller_work(self.model, 2, 2, 3, plan=self.plan))
        ledger = WorkLedger("short-affine", total_cap=total - 1)
        with patch.object(FrozenGenerator, "forward_low_state", side_effect=AssertionError("unfunded low")), \
             patch.object(c, "measure", side_effect=AssertionError("unfunded probe")):
            with self.assertRaises(BudgetExceeded):
                self.call(ledger=ledger)
        self.assertEqual(ledger.consumed_units, 0)


if __name__ == "__main__":
    unittest.main()
