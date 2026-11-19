"""Hand-input acceptance checks; no original TRAIN model/input is loaded."""

import json
import os
from pathlib import Path
import unittest

import numpy as np

from content_joint.adam4 import Adam4, compile_once
from content_joint.native_model import KEYS, Native12
from content_joint.objectives import IndependentObjective, NativeObjective
from content_joint.observe import sparse_metrics
from content_joint.work import forward_work, native_step_work
from content_reconcile.scoring import metrics
from data import DecodedObserver
from independent.accounting import BudgetExceeded, WorkLedger
from independent.learning import CachedObjective, objective_work, setup_work
from model import JointModel, softmax
from utility import certainty_equivalent


UNIT = Path(os.environ.get("CONTENT_JOINT_UNIT_DIR", "runs/content-joint-unit-v1-20261023"))
HAND = WorkLedger("hand-numerical-checks")
COMPILE = None


def setUpModule():
    global COMPILE
    UNIT.mkdir(parents=True, exist_ok=False)
    COMPILE = compile_once(UNIT / "adam4")


def tearDownModule():
    (UNIT / "hand-ledger.json").write_text(json.dumps(HAND.snapshot(), indent=2, sort_keys=True) + "\n")


class NativeChecks(unittest.TestCase):
    def setUp(self):
        self.base = JointModel(202, 12, 192, hidden=32, seed=701)
        self.model = Native12(self.base)
        self.rng = np.random.default_rng(711)
        self.x = self.rng.normal(0, .15, (3, 202))
        self.y = np.array([0, 4, 11])
        self.r = self.rng.uniform(-.35, 1., (12, 12, 12))
        HAND.charge_kernel("hand", "native_initialization", scalar_ops=396)

    def state(self, model=None):
        HAND.charge_kernel("hand", "native_forward", **forward_work(len(self.x)))
        return (self.model if model is None else model).forward(self.x)

    def value(self, objective, model=None):
        selected = self.model if model is None else model
        # Forward plus requested anchor/utility, not phantom backward/optimizer.
        from content_joint.analyze import add, single_head_parts
        parts = single_head_parts(12, objective.arm, len(self.x))
        HAND.charge_kernel("hand", "objective_value", **add(parts["anchor"], parts["utility"]))
        return objective.policy(self.state(selected), self.y)[0]

    def policy(self, objective, probabilities):
        from content_joint.analyze import add, single_head_parts
        parts = single_head_parts(12, objective.arm, len(probabilities))
        HAND.charge_kernel("hand", "policy_math", **add(parts["anchor"], parts["utility"]))
        return objective.policy(probabilities, self.y)

    def test_initial_conditioned_law(self):
        HAND.model_forward("hand", rows=3, input_dim=202, hidden=32, classes=12)
        p, q = self.base.forward(self.x)
        expected = p * q
        expected /= expected.sum(1, keepdims=True)
        HAND.charge_kernel("hand", "conditioning", scalar_ops=72, div_ops=36)
        np.testing.assert_allclose(self.state(), expected, rtol=2e-15, atol=2e-16)

    def test_anchor_preserves_original_average_and_point2(self):
        s = self.state()
        for arm in ("S", "H"):
            original = CachedObjective(arm, self.base)
            HAND.charge_kernel("hand", "old_anchor", **objective_work(arm, 3))
            loss, dt, di = original._policy_gradients_checked(s, s, self.y)
            native = NativeObjective(arm, self.model, self.r)
            actual, ds = self.policy(native, s)
            np.testing.assert_allclose(actual, loss, rtol=0, atol=2e-16)
            np.testing.assert_allclose(ds, dt + di, rtol=0, atol=2e-16)
            self.assertEqual(native.ce_weight, 1. if arm == "S" else .2)

    def test_original_independent_loss_unchanged(self):
        HAND.model_forward("hand", rows=3, input_dim=202, hidden=32, classes=12)
        p, q = self.base.forward(self.x)
        for arm in ("S", "H", "A", "N"):
            HAND.charge_kernel("hand", "original_objective_setup", **setup_work(self.base.dimensions, arm))
            old = CachedObjective(arm, self.base)
            new = IndependentObjective(arm, self.base,
                old.reward if old.reward is not None else self.r)
            HAND.charge_kernel("hand", "old_and_new_objectives", **{
                k: 2 * v for k, v in objective_work(arm, 3).items()})
            expected = old._policy_gradients_checked(p, q, self.y)
            actual = new._policy_gradients_checked(p, q, self.y)
            for a, b in zip(actual, expected):
                np.testing.assert_array_equal(a, b)

    def test_flat_A_N_logit_gradients(self):
        logits = self.rng.normal(size=(3, 12))
        for arm in ("A", "N"):
            objective = NativeObjective(arm, self.model, self.r)
            s = softmax(logits)
            _, analytic = self.policy(objective, s)
            for row, col in ((0, 0), (0, 7), (1, 4), (2, 11), (2, 2)):
                original = logits[row, col]
                logits[row, col] = original + 1e-5
                plus = self.policy(objective, softmax(logits))[0]
                logits[row, col] = original - 1e-5
                minus = self.policy(objective, softmax(logits))[0]
                logits[row, col] = original
                self.assertAlmostEqual((plus - minus) / 2e-5, analytic[row, col], places=9)
            reward = np.diagonal(self.r, axis1=1, axis2=2)[self.y]
            value = (np.sum(s * reward, axis=1) if arm == "A"
                     else certainty_equivalent(reward, s, 1.5, axis=1))
            self.policy(objective, s)
            self.assertAlmostEqual(float(value.mean()), objective.last["utility"], places=12)

    def test_encoder_and_head_gradients(self):
        for arm in ("H", "A", "N"):
            objective = NativeObjective(arm, self.model, self.r)
            _, gradients = objective.gradients(self.model, self.x, self.y)
            # This pure call executes forward/backward/objective without Adam.
            from content_joint.analyze import add, single_head_parts
            parts = single_head_parts(12, arm, 3)
            HAND.charge_kernel("hand", "pure_backprop", **add(
                parts["forward"], parts["backward"], parts["anchor"], parts["utility"]))
            for key, index in (("encoder", (2, 4)), ("bias", (4,)),
                               ("shared", (4, 7)), ("shared_bias", (7,))):
                value = self.model.params[key][index]
                self.model.params[key][index] = value + 1e-5
                plus = self.value(objective)
                self.model.params[key][index] = value - 1e-5
                minus = self.value(objective)
                self.model.params[key][index] = value
                self.assertAlmostEqual((plus - minus) / 2e-5, gradients[key][index], places=8)

    def test_sparse_full_Q_and_actual_semantics(self):
        s = self.state()
        distances = self.rng.uniform(0, .1, (12, 12))
        image_map = np.array([1, 0] + list(range(2, 12)))
        observer = DecodedObserver((np.arange(12), image_map, None, distances), self.r)
        joint = np.zeros((3, 12, 12))
        joint[:, np.arange(12), np.arange(12)] = s
        sparse = sparse_metrics(s, self.y, observer, HAND, "hand")
        full = metrics(joint, self.r[self.y], self.y, observer, HAND, "hand")
        for key in sparse:
            np.testing.assert_allclose(sparse[key], full[key], rtol=0, atol=1e-15)
        self.assertGreater(float(sparse["semantic_disagreement"].mean()), 0)

    def test_zero_support_and_first_index_ties(self):
        s = np.full((3, 12), 1 / 11)
        s[np.arange(3), self.y] = 0
        with self.assertRaises(ValueError):
            NativeObjective("H", self.model, self.r).policy(s, self.y)
        np.testing.assert_array_equal(np.ones((3, 12)).argmax(1), np.zeros(3))

    def test_Adam4_clocks_moments_displacement_and_decoder(self):
        reference = Native12(self.base)
        for j, key in enumerate(KEYS):
            shape = self.model.params[key].shape
            moment = (np.full(shape, .003 * (j + 1)), np.full(shape, .007 * (j + 1)), 2 + j)
            self.model._moments[key] = tuple(a.copy() if isinstance(a, np.ndarray) else a for a in moment)
            reference._moments[key] = tuple(a.copy() if isinstance(a, np.ndarray) else a for a in moment)
        optimizer = Adam4(self.model, COMPILE["library_path"])
        decoder = self.model.params["decoder"].copy()
        initial = {key: self.model.params[key].copy() for key in KEYS}
        for iteration in range(3):
            gradients = {key: self.rng.normal(0, 5., self.model.params[key].shape) for key in KEYS}
            if iteration == 2:
                gradients = {key: np.zeros_like(value) for key, value in gradients.items()}
            optimizer.apply_gradients(self.model, gradients, .01)
            reference.apply_gradients(gradients, .01)
            from content_joint.analyze import single_head_parts
            work = single_head_parts(12, "H", 3)["optimizer"]
            HAND.charge_kernel("hand", "two_Adam_implementations", **{key: 2 * value for key, value in work.items()})
            for key in KEYS:
                np.testing.assert_allclose(self.model.params[key], reference.params[key], atol=2e-15, rtol=0)
                for actual, expected in zip(self.model._moments[key][:2], reference._moments[key][:2]):
                    np.testing.assert_allclose(actual, expected, atol=2e-15, rtol=0)
                self.assertEqual(self.model._moments[key][2], reference._moments[key][2])
        self.assertTrue(all(np.any(self.model.params[k] != initial[k]) for k in KEYS))
        np.testing.assert_array_equal(self.model.params["decoder"], decoder)
        self.assertNotIn("decoder", self.model._moments)

    def test_Adam4_rejects_partial_alias_and_replaced_state(self):
        optimizer = Adam4(self.model, COMPILE["library_path"])
        original = self.model.digest()
        gradients = {key: np.ones_like(self.model.params[key]) for key in KEYS}
        with self.assertRaises(ValueError):
            optimizer.apply_gradients(self.model, {"bias": gradients["bias"]}, .01)
        with self.assertRaises(ValueError):
            optimizer.apply_gradients(self.model, {key: self.model.params[key] for key in KEYS}, .01)
        self.assertEqual(self.model.digest(), original)
        self.model.params["bias"] = self.model.params["bias"].copy()
        with self.assertRaises(ValueError):
            optimizer.apply_gradients(self.model, gradients, .01)

    def test_budget_rejection_precedes_parameter_update(self):
        optimizer = Adam4(self.model, COMPILE["library_path"])
        objective = NativeObjective("A", self.model, self.r, optimizer)
        ledger = WorkLedger("too-small", 1)
        digest = self.model.digest()
        with self.assertRaises(BudgetExceeded):
            objective.step(self.model, self.x, self.y, .01, ledger=ledger)
        self.assertEqual(self.model.digest(), digest)
        self.assertEqual(self.model.updates, 0)

    def test_save_reload_is_exact(self):
        path = UNIT / "hand-model.npz"
        self.model.save(path)
        restored = Native12.load(path)
        self.assertEqual(restored.digest(), self.model.digest())
        np.testing.assert_array_equal(self.state(), self.state(restored))


if __name__ == "__main__":
    unittest.main(verbosity=2)
