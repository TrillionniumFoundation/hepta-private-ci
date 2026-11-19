import copy
import unittest
from unittest.mock import Mock, patch

import numpy as np

from independent.accounting import BudgetExceeded, WorkLedger
from independent.learning import CachedObjective, setup_work, step_work
from model import JointModel, softmax
from utility import joint_value_and_grad


class EfficientLearningTests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(19851)
        self.model = JointModel(19, 12, 192, hidden=4, seed=23)
        self.x = self.rng.normal(size=(7, 19))
        self.y = self.rng.integers(12, size=7)

    def test_cached_objective_matches_original_joint_gradients(self):
        p = softmax(self.rng.normal(size=(7, 12)))
        q = softmax(self.rng.normal(size=(7, 12)))
        for arm, rho in (("A", 0), ("N", 1.5)):
            objective = CachedObjective(arm, self.model)
            ce_loss, ce_dt, ce_di = CachedObjective("H", self.model).policy_gradients(p, q, self.y)
            utility, dt, di = joint_value_and_grad(p, q, objective.reward[self.y], rho)
            np.testing.assert_allclose(objective.utility_values(p, q, self.y), utility, atol=2e-15)
            loss, actual_dt, actual_di = objective.policy_gradients(p, q, self.y)
            self.assertAlmostEqual(loss, ce_loss - utility.mean(), places=12)
            np.testing.assert_allclose(actual_dt, ce_dt + dt, atol=2e-15, rtol=2e-12)
            np.testing.assert_allclose(actual_di, ce_di + di, atol=2e-15, rtol=2e-12)

    def test_one_forward_backprop_matches_reference_parameter_update(self):
        for arm in ("S", "H", "A", "N"):
            actual, expected = self.model.clone(), self.model.clone()
            objective = CachedObjective(arm, actual)
            p, q = expected.forward(self.x)
            loss, dt, di = objective.policy_gradients(p, q, self.y)
            expected.train_step(self.x, dt, di, 0.003)
            with (patch.object(actual, "_input", wraps=actual._input) as inputs,
                  patch.object(actual, "_forward", side_effect=AssertionError("duplicate input check")),
                  patch.object(objective, "_inputs", side_effect=AssertionError("rechecked generated policy"))):
                self.assertAlmostEqual(objective.step(actual, self.x, self.y, 0.003), loss)
                self.assertEqual(inputs.call_count, 1)
            for key in actual.params:
                np.testing.assert_array_equal(actual.params[key], expected.params[key])
            for key in ("decoder", "decoder_bias"):
                np.testing.assert_array_equal(actual.params[key], self.model.params[key])

    def assert_model_state_identical(self, actual, expected):
        self.assertEqual(actual.dimensions, expected.dimensions)
        self.assertEqual(actual.updates, expected.updates)
        self.assertEqual(set(actual.params), set(expected.params))
        self.assertEqual(set(actual._moments), set(expected._moments))
        for key in actual.params:
            self.assertEqual(actual.params[key].dtype, expected.params[key].dtype)
            self.assertEqual(actual.params[key].shape, expected.params[key].shape)
            self.assertEqual(actual.params[key].tobytes(), expected.params[key].tobytes(), key)
        for key, (mean, variance, step) in actual._moments.items():
            expected_mean, expected_variance, expected_step = expected._moments[key]
            self.assertEqual(mean.tobytes(), expected_mean.tobytes(), key)
            self.assertEqual(variance.tobytes(), expected_variance.tobytes(), key)
            self.assertEqual(step, expected_step, key)

    def test_injected_optimizer_receives_unchanged_content_gradients_and_preserves_two_updates(self):
        content = {"encoder", "bias", "text", "text_bias", "image", "image_bias"}
        for arm in ("S", "H", "A", "N"):
            with self.subTest(arm=arm):
                actual, expected = self.model.clone(), self.model.clone()
                actual_ledger, expected_ledger = WorkLedger(arm), WorkLedger(arm)
                optimizer = Mock(spec=["apply_gradients"])
                optimizer.apply_gradients.side_effect = lambda model, grads, lr: model.apply_gradients(grads, lr)
                injected = CachedObjective(arm, actual, ledger=actual_ledger, optimizer=optimizer)
                legacy = CachedObjective(arm, expected, ledger=expected_ledger)
                self.assertIs(injected.optimizer, optimizer)
                self.assertIsNone(legacy.optimizer)
                for index, (x, y, lr) in enumerate(((self.x, self.y, 0.003),
                                                    (self.x[::-1], self.y[::-1], 0.001)), 1):
                    with patch.object(expected, "apply_gradients", wraps=expected.apply_gradients) as reference:
                        expected_loss = legacy.step(expected, x, y, lr, ledger=expected_ledger)
                    actual_loss = injected.step(actual, x, y, lr, ledger=actual_ledger)
                    self.assertEqual(optimizer.apply_gradients.call_count, index)
                    passed_model, gradients, passed_lr = optimizer.apply_gradients.call_args.args
                    reference.assert_called_once()
                    reference_gradients, reference_lr = reference.call_args.args
                    self.assertIs(passed_model, actual)
                    self.assertEqual((passed_lr, reference_lr), (lr, lr))
                    self.assertEqual(set(gradients), content)
                    self.assertEqual(set(reference_gradients), content)
                    for key in content:
                        self.assertEqual(gradients[key].shape, reference_gradients[key].shape)
                        self.assertEqual(gradients[key].tobytes(), reference_gradients[key].tobytes(), key)
                    self.assertEqual(np.float64(actual_loss).tobytes(), np.float64(expected_loss).tobytes())
                    self.assert_model_state_identical(actual, expected)
                    self.assertEqual(actual_ledger.snapshot(), expected_ledger.snapshot())
                self.assertIs(injected.optimizer, optimizer)

    def test_budget_rejection_never_calls_injected_optimizer_or_changes_model(self):
        for arm in ("S", "H", "A", "N"):
            with self.subTest(arm=arm):
                model = self.model.clone()
                optimizer = Mock(spec=["apply_gradients"])
                objective = CachedObjective(arm, model, optimizer=optimizer)
                expected = copy.deepcopy(model)
                ledger = WorkLedger(arm, total_cap=1)
                before = ledger.snapshot()
                with self.assertRaises(BudgetExceeded):
                    objective.step(model, self.x, self.y, 0.003, ledger=ledger)
                optimizer.apply_gradients.assert_not_called()
                self.assert_model_state_identical(model, expected)
                self.assertEqual(ledger.snapshot(), before)

    def test_invalid_optimizer_rejects_before_cache_preparation(self):
        for arm in ("S", "H", "A", "N"):
            for optimizer in (object(), {"apply_gradients": lambda *args: None},
                              Mock(apply_gradients=1)):
                with self.subTest(arm=arm, optimizer=type(optimizer).__name__):
                    ledger = WorkLedger(arm)
                    before = ledger.snapshot()
                    with patch("independent.learning.outcome_table", side_effect=AssertionError("unused cache")):
                        with self.assertRaisesRegex(TypeError, "optimizer must provide apply_gradients"):
                            CachedObjective(arm, self.model, optimizer=optimizer, ledger=ledger)
                    self.assertEqual(ledger.snapshot(), before)

    def test_supervised_arms_never_prepare_or_execute_joint_utility(self):
        for arm in ("S", "H"):
            ledger = WorkLedger(arm)
            with patch("independent.learning.outcome_table", side_effect=AssertionError("unused reward")):
                objective = CachedObjective(arm, self.model, ledger=ledger)
                objective.step(self.model.clone(), self.x, self.y, 0.003, ledger=ledger)
            self.assertNotIn("joint_utility_calls", ledger.totals)
            self.assertNotIn("objective_cache_builds", ledger.totals)
            self.assertEqual(ledger.totals["model_forward_calls"], 1)
        for arm, forbidden in (("A", "entropic_gradient_calls"), ("N", "additive_gradient_calls")):
            ledger = WorkLedger(arm)
            objective = CachedObjective(arm, self.model, ledger=ledger)
            objective.step(self.model.clone(), self.x, self.y, 0.003, ledger=ledger)
            self.assertEqual(ledger.totals["joint_utility_calls"], 1)
            self.assertNotIn(forbidden, ledger.totals)

    def test_cheaper_arm_can_spend_identical_cap_on_more_useful_updates(self):
        probe = WorkLedger("probe")
        n = len(self.x)
        h_cost = probe.estimate_kernel(**step_work(self.model.dimensions, "H", n))
        n_cost = probe.estimate_kernel(**step_work(self.model.dimensions, "N", n))
        self.assertLess(h_cost, n_cost)
        cap = 6 * n_cost + probe.estimate_kernel(**setup_work(self.model.dimensions, "N"))
        updates = {}
        for arm in ("H", "N"):
            ledger, model = WorkLedger(arm, total_cap=cap), self.model.clone()
            objective = CachedObjective(arm, model, ledger=ledger)
            cost = ledger.estimate_kernel(**step_work(model.dimensions, arm, n))
            count = 0
            while cost <= ledger.remaining_units:
                objective.step(model, self.x, self.y, 0.003, ledger=ledger)
                count += 1
            self.assertEqual(ledger.totals["content_updates"], count)
            self.assertLessEqual(ledger.consumed_units, cap)
            updates[arm] = count
        self.assertGreater(updates["H"], updates["N"])

    def test_budget_rejection_is_atomic_for_setup_and_whole_update(self):
        ledger = WorkLedger("short", total_cap=1)
        before = ledger.snapshot()
        with patch("independent.learning.outcome_table", side_effect=AssertionError("no computation before admission")):
            with self.assertRaises(BudgetExceeded):
                CachedObjective("N", self.model, ledger=ledger)
        self.assertEqual(ledger.snapshot(), before)
        objective = CachedObjective("N", self.model)
        model_before = copy.deepcopy(self.model.__dict__)
        with patch.object(self.model, "_forward", side_effect=AssertionError("no forward before admission")):
            with self.assertRaises(BudgetExceeded):
                objective.step(self.model, self.x, self.y, 0.003, ledger=ledger)
        self.assertEqual(ledger.snapshot(), before)
        self.assertEqual(self.model.updates, model_before["updates"])
        self.assertEqual(self.model._moments, model_before["_moments"])
        for key, value in model_before["params"].items():
            np.testing.assert_array_equal(self.model.params[key], value)

    def test_decoder_binding_and_bad_inputs_reject_before_training(self):
        objective = CachedObjective("N", self.model)
        changed = self.model.clone()
        changed.params["decoder"][0, 0] += 0.01
        ledger = WorkLedger("validation")
        before = ledger.snapshot()
        with self.assertRaisesRegex(ValueError, "decoder changed"):
            objective.step(changed, self.x, self.y, 0.003, ledger=ledger)
        for labels in (self.y.astype(float), np.full(7, 12), np.zeros(6, dtype=int)):
            with self.assertRaises(ValueError):
                objective.step(self.model, self.x, labels, 0.003, ledger=ledger)
        for inputs in (self.x[:, :-1], np.empty((0, 19)), np.full_like(self.x, float("nan"))):
            with self.assertRaises(ValueError):
                objective.step(self.model, inputs, self.y, 0.003, ledger=ledger)
        self.assertEqual(ledger.snapshot(), before)

    def test_public_policy_and_value_interfaces_keep_strict_validation(self):
        objective = CachedObjective("N", self.model)
        p, q = self.model.forward(self.x)
        invalid = []
        for value in (float("nan"), -0.01):
            changed = p.copy()
            changed[0, 0] = value
            invalid.append((changed, q, self.y))
        invalid.extend(((p * 0.5, q, self.y), (p, q[:, :-1], self.y),
                        (p, q, self.y.astype(float)), (p, q, np.full(7, 12))))
        for method in (objective.policy_gradients, objective.utility_values):
            for args in invalid:
                with self.assertRaises(ValueError):
                    method(*args)


if __name__ == "__main__":
    unittest.main()
