"""Handmade proofs only: no experiment dataset, formal split, or timing wave."""

import unittest
from unittest.mock import patch

import numpy as np

from independent.accounting import BudgetExceeded, WorkLedger
from independent.learning import CachedObjective
from model import JointModel, softmax
from ndu_training.diagnostics import flat, gradient
from ndu_training.estimators import Sampler, WeightedObjective
from utility import certainty_equivalent


class HandmadeTests(unittest.TestCase):
    def test_weighted_gradients_are_derivatives_of_per_request_mean(self):
        rng = np.random.default_rng(71)
        model = JointModel(202, 12, 192, hidden=3)
        z, v, y, w = (
            rng.normal(size=(4, 12)),
            rng.normal(size=(4, 12)),
            np.array([0, 3, 7, 11]),
            np.array([0.4, 1.2, 0.9, 1.5]),
        )
        for arm in ("A", "N"):
            obj = WeightedObjective(arm, model)
            obj.row_weights = w
            p, q = softmax(z), softmax(v)
            loss, dt, di = obj.policy_gradients(p, q, y)
            independent = CachedObjective(arm, model)
            values = independent.utility_values(p, q, y)
            expected = np.mean(
                w
                * (
                    -0.1 * (np.log(p[np.arange(4), y]) + np.log(q[np.arange(4), y]))
                    - values
                )
            )
            self.assertAlmostEqual(loss, expected, places=13)
            for logits, analytic in ((z, dt), (v, di)):
                for index in np.ndindex(logits.shape):
                    original, epsilon = logits[index], 1e-5
                    logits[index] = original + epsilon
                    high = obj.policy_gradients(softmax(z), softmax(v), y)[0]
                    logits[index] = original - epsilon
                    low = obj.policy_gradients(softmax(z), softmax(v), y)[0]
                    logits[index] = original
                    self.assertAlmostEqual(
                        (high - low) / (2 * epsilon), analytic[index], places=9
                    )

    def test_exact_stratified_expectation_preserves_original_population(self):
        labels = np.repeat(np.arange(12), np.arange(1, 13))
        sampler = Sampler(labels, "stratified", 11)
        self.assertEqual(int(sampler.counts.sum()), 64)
        self.assertTrue(np.all(sampler.counts > 0))
        # Enumerate each stratum's conditional expectation, without simulation.
        vector = np.column_stack((labels, labels**2, np.arange(len(labels))))
        actual = sum(
            c / 64 * (64 * p / c) * vector[m].mean(0)
            for c, p, m in zip(sampler.counts, sampler.mass, sampler.members)
        )
        np.testing.assert_allclose(actual, vector.mean(0), rtol=0, atol=1e-12)
        # Whole-label conditional means contribute zero estimator variance.
        self.assertGreater(float(np.var(labels) / 64), 0)
        self.assertEqual(
            sum(
                p * p / c * float(np.var(labels[m]))
                for c, p, m in zip(sampler.counts, sampler.mass, sampler.members)
            ),
            0,
        )

    def test_joint_paths_and_requests_cannot_be_replaced_by_marginals(self):
        rho = 1.5
        rewards, pa, pb = (
            np.array([[1.0, -0.35], [-0.35, 1.0]]),
            np.array([0.4, 0.6]),
            np.array([[0.9, 0.1], [0.2, 0.8]]),
        )
        joint = pa[:, None] * pb
        direct = certainty_equivalent(rewards.ravel(), joint.ravel(), rho)
        conditional = certainty_equivalent(rewards, pb, rho, axis=1)
        recursive = certainty_equivalent(conditional, pa, rho)
        self.assertAlmostEqual(float(direct), float(recursive), places=14)
        wrong_joint = pa[:, None] * (pa @ pb)[None, :]
        wrong = certainty_equivalent(rewards.ravel(), wrong_joint.ravel(), rho)
        self.assertGreater(abs(float(direct - wrong)), 0.05)
        per_request = np.array([0.0, 1.0])
        self.assertGreater(
            abs(
                per_request.mean()
                - float(certainty_equivalent(per_request, np.array([0.5, 0.5]), rho))
            ),
            0.1,
        )

    def test_iid_updates_are_identical_and_weighted_refusal_is_atomic(self):
        rng = np.random.default_rng(1)
        x, y = rng.normal(size=(4, 202)), np.array([1, 2, 4, 7])
        base = JointModel(202, 12, 192, hidden=3)
        for arm in ("A", "N"):
            old, new = base.clone(), base.clone()
            CachedObjective(arm, old).step(old, x, y, 0.003)
            WeightedObjective(arm, new).step(new, x, y, 0.003)
            self.assertEqual(old.digest(), new.digest())
            obj = WeightedObjective(arm, new)
            obj.row_weights = np.ones(4)
            ledger = WorkLedger(arm, total_cap=1)
            before, digest = ledger.snapshot(), new.digest()
            with self.assertRaises(BudgetExceeded):
                obj.step(new, x, y, 0.003, ledger=ledger)
            self.assertEqual(ledger.snapshot(), before)
            self.assertEqual(new.digest(), digest)

    def test_invalid_weights(self):
        model = JointModel(202, 12, 192, hidden=2)
        obj = WeightedObjective("N", model)
        for weights in (np.zeros(4), np.array([1.0, 1.0, np.nan, 1.0]), np.ones(3)):
            obj.row_weights = weights
            with self.assertRaises(ValueError):
                obj.policy_gradients(
                    np.ones((4, 12)) / 12, np.ones((4, 12)) / 12, np.arange(4)
                )
    def test_diagnostic_parameter_gradient_matches_applied_gradient_without_adam_work(
        self,
    ):
        rng = np.random.default_rng(231)
        x, y = rng.normal(size=(4, 202)), np.array([0, 1, 3, 10])
        weights = np.array([0.7, 1.3, 0.8, 1.2])
        for arm in ("A", "N"):
            model = JointModel(202, 12, 192, hidden=3)
            obj = WeightedObjective(arm, model)
            obj.row_weights = weights
            with patch.object(model, "apply_gradients") as capture:
                obj.step(model, x, y, 0.003)
            ledger = WorkLedger("gradient")
            actual = gradient(model, x, y, obj, weights, ledger)
            np.testing.assert_array_equal(actual, flat(capture.call_args.args[0]))
            self.assertNotIn("optimizer_updates", ledger.totals)
            self.assertEqual(ledger.totals["model_forward_calls"], 1)
            self.assertEqual(ledger.totals["model_backward_calls"], 1)


if __name__ == "__main__":
    unittest.main()
