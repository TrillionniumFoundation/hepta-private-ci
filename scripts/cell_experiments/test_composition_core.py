"""Numerical fixtures only; these tests do not establish learning qualification."""

import copy
import unittest

import numpy as np

from cell_experiments import composition_core as c
from hepta_cells.semantic import LocalHead, LocalObjective


def prepared():
    """The same four authored A inputs in the numeric core's admitted-row shape."""
    rows = []
    for i, value in enumerate((-2.0, -1.0, 1.0, 2.0)):
        identity = f"fixture-A-{i}"
        rows.append(
            dict(
                task_id=identity,
                source_id=f"A-source-{i % 2}",
                family_id="A-sign",
                split="A",
                timestamp=float(10 + i),
                features=[value, 1.0],
                target=int(value > 0),
                observation_digest=c.digest({"fixture_id": identity, "value": value}),
            )
        )
    return rows


class NumericalTests(unittest.TestCase):
    def test_sparse_router_and_every_head_match_finite_differences(self):
        original = c.SparseCircuit(2, 2, 3, 2, "learned_sparse", 2)
        original.router = LocalHead(
            [[0.2, 0.0, -0.1], [0.1, 0.3, -0.2]], [0.3, 0.2, -1.0]
        )
        original.heads = [
            LocalHead([[0.1 + i * 0.2, -0.3], [0.4, i * 0.1]], [i * 0.1, -0.2])
            for i in range(3)
        ]
        x, target = np.array([[0.7, -0.2], [-0.4, 0.8]]), np.array([1, 0])
        trained, rate, epsilon = copy.deepcopy(original), 0.01, 1e-6
        trained.update(x, target, rate)

        def loss(model):
            return LocalObjective("cross_entropy", 2, "fixture").loss_and_gradient(
                model.forward(x)[0], target
            )[0]

        for which in range(4):
            before = original.router if which == 3 else original.heads[which]
            after = trained.router if which == 3 else trained.heads[which]
            for attribute in ("first", "bias"):
                value = getattr(before, attribute)
                analytic = (value - getattr(after, attribute)) / rate
                for index in np.ndindex(value.shape):
                    losses = []
                    for sign in (-1, 1):
                        modified = copy.deepcopy(original)
                        params = {
                            "first": before.first.copy(),
                            "bias": before.bias.copy(),
                        }
                        params[attribute][index] += sign * epsilon
                        replacement = LocalHead(**params)
                        if which == 3:
                            modified.router = replacement
                        else:
                            modified.heads[which] = replacement
                        losses.append(loss(modified))
                    self.assertAlmostEqual(
                        analytic[index],
                        (losses[1] - losses[0]) / (2 * epsilon),
                        places=7,
                    )

    def test_real_sgd_reduces_loss_and_respects_mac_without_mutating_parent(self):
        rows = [r for r in prepared() if r["split"] == "A"]
        original = c.SparseCircuit(2, 2, 1, 1, "single", 3)
        before = original.digest
        initial_loss = c.evaluate(original, rows)["loss"]
        trained, receipt = c.fit(
            original, rows, {"max_examples": 60, "max_train_mac": 400}, 0.2, 30
        )
        self.assertEqual(original.digest, before)
        self.assertNotEqual(trained.digest, before)
        self.assertLess(c.evaluate(trained, rows)["loss"], initial_loss / 3)
        self.assertEqual((receipt["updates"], receipt["linear_mac"]), (50, 400))
        self.assertEqual(receipt["attempted_updates"], receipt["updates"])
        self.assertFalse(receipt["full_cost_known"])

    def test_per_source_budget_is_enforced_for_uneven_source_sizes(self):
        rows = [r for r in prepared() if r["split"] == "A"]
        rows[1]["source_id"] = rows[0]["source_id"]
        model = c.SparseCircuit(2, 2, 1, 1, "single", 3)
        _, receipt = c.fit(
            model,
            rows,
            {
                "max_examples": 30,
                "max_train_mac": 1000,
                "per_source_max_examples": 3,
                "per_source_max_train_mac": 24,
            },
            0.1,
            20,
        )
        self.assertEqual(sorted(receipt["examples_by_source"].values()), [3, 3])
        self.assertEqual(sorted(receipt["mac_by_source"].values()), [24, 24])

    def test_insufficient_budget_is_blocked_and_failed_arithmetic_is_not_no_update(
        self,
    ):
        row = [r for r in prepared() if r["split"] == "A"][:1]
        model = c.SparseCircuit(2, 2, 1, 1, "single", 1)
        same, empty = c.fit(model, row, {"max_examples": 1, "max_train_mac": 7}, 0.1, 1)
        self.assertEqual(
            (empty["status"], same.digest), ("BLOCKED_BUDGET", model.digest)
        )
        model.heads = [LocalHead(np.full((2, 2), 1e308), [0, 0])]
        row[0]["features"] = [1e308, 1e308]
        with np.errstate(over="ignore", invalid="ignore"):
            _, failed = c.fit(
                model, row, {"max_examples": 1, "max_train_mac": 8}, 1.0, 1
            )
        self.assertEqual(failed["status"], "FAILED")
        self.assertEqual(failed["attempted_updates"], 1)
        self.assertFalse(failed["failed_attempt_arithmetic_known"])
        self.assertGreaterEqual(failed["wall_ns"], 0)

    def test_restore_verifies_parameters_and_ablation_changes_actual_forward(self):
        model = c.SparseCircuit(2, 2, 3, 2, "fixed", 5)
        model.heads = [LocalHead([[1 + i, 3 + i], [0, 0]], [0, 0]) for i in range(3)]
        x = np.array([[1.0, 0.0]])
        restored = c.SparseCircuit.restore(model.record(), model.digest)
        original = model.forward(x)[0]
        np.testing.assert_array_equal(restored.forward(x)[0], original)
        edge, routes, _ = restored.forward(x, drop_edge=(0, 0))
        self.assertEqual(edge[0, 1], original[0, 1])
        self.assertLess(edge[0, 0], original[0, 0])
        self.assertEqual(restored.cost(routes, drop_edge=(0, 0))["message_bytes"], 24)
        without, routes, _ = restored.forward(x, drop_cell=0)
        np.testing.assert_array_equal(without, [[2, 4]])
        self.assertEqual(restored.cost(routes)["messages"], 1)
        corrupted = model.record()
        corrupted["heads"][0]["bias"][0] += 1
        with self.assertRaisesRegex(ValueError, "model bytes"):
            c.SparseCircuit.restore(corrupted, model.digest)


if __name__ == "__main__":
    unittest.main()
