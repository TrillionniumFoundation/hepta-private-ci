"""Replica-resistant selection, exact scatter, and frozen private-state custody."""

import unittest
from unittest.mock import patch

import numpy as np

from cell_batch_runtime import BatchRuntimeError, BatchedCellRuntime
from cell_learning_models import NumpyCellHead
from cell_logical_routing import LogicalCellRouter

IDENTITY = "a" * 64
SOURCES = ("b" * 64, "c" * 64)


class LogicalRoutingTests(unittest.TestCase):
    def heads(self, mode="gated"):
        x = np.random.default_rng(9).normal(size=(16, 4))
        heads = []
        for index in range(3):
            head = NumpyCellHead(4, 2, mode, rank=2, seed=index)
            head.train(x, (x[:, index] > 0).astype(int), steps=12)
            head.feature_identity = IDENTITY
            heads.append(head)
        return heads

    def predict(self, router, x=None, **options):
        return router.predict(np.ones((2, 4)) if x is None else x, source_digests=SOURCES,
                              feature_identity=IDENTITY, generation=1, **options)

    def test_all_unique_scatter_equals_original_physical_and_scalar_outputs(self):
        x = np.random.default_rng(10).normal(size=(2, 4))
        for mode in ("linear", "gated", "residual"):
            with self.subTest(mode=mode):
                heads = self.heads(mode)
                physical = [heads[i % 3] for i in range(64)]
                ids, tasks = [f"cell-{i}" for i in range(64)], [f"task-{i % 3}" for i in range(64)]
                logical = LogicalCellRouter(physical, ids, tasks, IDENTITY)
                reference = BatchedCellRuntime(physical, ids, tasks, IDENTITY)
                result = self.predict(logical, x)
                original = self.predict(reference, x)
                np.testing.assert_array_equal(result["logits"], original["logits"])
                scalar = np.stack([head.predict_logits(x) for head in physical], axis=1)
                np.testing.assert_allclose(result["logits"], scalar, atol=1e-12, rtol=1e-12)
                self.assertTrue(result["served_mask"].all())
                self.assertEqual(result["source_digests"], SOURCES)
                self.assertEqual(result["physical_cell_ids"], tuple(ids))
                self.assertEqual(result["head_evaluations"], 6)
                self.assertEqual(logical.accounting()["retained_private_head_states"], 3)
                self.assertEqual(logical.accounting()["physical_cell_ids"], 64)

    def test_physical_replicas_do_not_crowd_logical_top_k(self):
        heads = self.heads()
        for repeats in (1, 4, 32):
            physical = heads * repeats
            router = LogicalCellRouter(physical, [f"c{i}" for i in range(len(physical))],
                [f"t{i % 3}" for i in range(len(physical))], IDENTITY)
            result = self.predict(router, top_k=2, router_scores=np.array([[3, 2, 1], [1, 2, 3]]))
            self.assertEqual(result["selected_logical_indices"].tolist(), [[0, 1], [2, 1]])
            self.assertEqual(result["served_mask"].sum(axis=1).tolist(), [2 * repeats] * 2)
            self.assertEqual(result["head_evaluations"], 4)
            self.assertTrue((result["logits"][~result["served_mask"]] == 0).all())

    def test_same_task_different_parameters_and_same_parameters_different_tasks_stay_unique(self):
        first, second, _ = self.heads()
        router = LogicalCellRouter([first, second, first, first], ["a", "b", "c", "d"],
                                   ["same", "same", "same", "other"], IDENTITY)
        self.assertEqual(router.physical_to_logical.tolist(), [0, 1, 0, 2])
        self.assertEqual(router.accounting()["retained_private_head_states"], 3)

    def test_conflicting_prototypes_and_unbound_or_changed_state_reject(self):
        head = self.heads()[0]
        with self.assertRaisesRegex(BatchRuntimeError, "conflicting"):
            LogicalCellRouter([head, head], ["a", "b"], ["t", "t"], IDENTITY,
                              router_keys=np.array([[1, 0, 0, 0], [0, 1, 0, 0]]))
        head.feature_identity = "d" * 64
        with self.assertRaisesRegex(BatchRuntimeError, "feature identity"):
            LogicalCellRouter([head], ["a"], ["t"], IDENTITY)
        head.feature_identity = IDENTITY
        head.W[:] += 1
        with self.assertRaisesRegex(BatchRuntimeError, "training receipt"):
            LogicalCellRouter([head], ["a"], ["t"], IDENTITY)

    def test_external_learning_and_prototype_mutation_do_not_change_serving_snapshot(self):
        head = self.heads()[0]
        keys = np.ones((2, 4))
        router = LogicalCellRouter([head, head], ["a", "b"], ["t", "t"], IDENTITY, router_keys=keys)
        before = self.predict(router)
        head.train(np.eye(4), np.array([0, 1, 0, 1]), steps=3)
        keys[:] = 99
        after = self.predict(router)
        np.testing.assert_array_equal(before["logits"], after["logits"])
        with self.assertRaises(ValueError):
            router.physical_to_logical.setflags(write=True)
        self.assertEqual(after["private_parameter_updates"], 0)

    def test_stale_scope_bad_top_k_and_budget_reject_before_dispatch(self):
        heads = self.heads()
        router = LogicalCellRouter(heads, ["a", "b", "c"], ["a", "b", "c"], IDENTITY)
        for options in ({"top_k": True}, {"top_k": 4}, {"top_k": 1},
                        {"router_scores": np.zeros((2, 4))}):
            with self.subTest(options=options), self.assertRaises(BatchRuntimeError):
                self.predict(router, **options)
        with self.assertRaises(BatchRuntimeError):
            router.predict(np.ones((2, 4)), source_digests=SOURCES,
                           feature_identity="f" * 64, generation=1)
        with patch("cell_logical_routing.MAX_OUTPUT_BYTES", 1), self.assertRaises(BatchRuntimeError):
            self.predict(router)
        self.assertEqual(router.runtime.dispatch_calls, 0)


if __name__ == "__main__":
    unittest.main()
