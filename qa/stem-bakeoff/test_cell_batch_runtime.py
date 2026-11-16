"""Real learned-array parity and scoped cache/dispatch regressions."""

import unittest

import numpy as np

from cell_batch_runtime import BatchRuntimeError, BatchedCellRuntime, GlobalFeatureCache
from cell_learning_models import NumpyCellHead

IDENTITY = "a" * 64
SOURCES = ("b" * 64, "c" * 64)


class BatchedRuntimeTests(unittest.TestCase):
    def heads(self, mode):
        x = np.random.default_rng(9).normal(size=(16, 5))
        return [self.trained(x, (x[:, i] > 0).astype(int), mode, i) for i in range(3)]

    def trained(self, x, labels, mode, seed):
        head = NumpyCellHead(5, 2, mode, rank=2, seed=seed)
        head.train(x, labels, steps=25)
        return head

    def pool(self, mode="residual", **options):
        heads = self.heads(mode)
        return heads, BatchedCellRuntime(heads, ["cell-a", "cell-b", "cell-c"],
                                         ["task-a", "task-b", "task-c"], IDENTITY, **options)

    def test_vectorized_matches_separately_trained_scalar_heads_and_selection(self):
        x = np.random.default_rng(10).normal(size=(2, 5))
        scores = np.array([[0, 2, 1], [2, 0, 1]])
        for mode in ("linear", "gated", "residual"):
            with self.subTest(mode=mode):
                heads, pool = self.pool(mode)
                out = pool.predict(x, source_digests=SOURCES, feature_identity=IDENTITY,
                                   generation=1, top_k=2, router_scores=scores)
                self.assertEqual(out["selected_cell_ids"], [["cell-b", "cell-c"], ["cell-a", "cell-c"]])
                expected = np.stack([np.stack([heads[i].predict_logits(x[row:row+1])[0]
                                             for i in ids]) for row, ids in enumerate([[1, 2], [0, 2]])])
                np.testing.assert_allclose(out["logits"], expected, atol=1e-12, rtol=1e-12)
                self.assertEqual((out["head_evaluations"], out["head_array_batches"],
                                  out["encoder_invocations_by_runtime"]), (4, 2, 0))
                self.assertEqual(pool.accounting()["unique_parameter_states"], 3)

    def test_owned_weights_and_cache_cannot_alias_or_become_writeable(self):
        heads, pool = self.pool(cache_bytes=80)
        x = np.ones((2, 5))
        before = pool.predict(x, source_digests=SOURCES, feature_identity=IDENTITY, generation=1)
        heads[0].W[:] = 999
        x[:] = 888
        after = pool.predict_cached(SOURCES, feature_identity=IDENTITY, generation=1)
        np.testing.assert_array_equal(before["logits"], after["logits"])
        cached = pool.cache.get((IDENTITY, 1, SOURCES[0]))
        with self.assertRaises(ValueError):
            cached.setflags(write=True)
        with self.assertRaises(ValueError):
            pool._params["W"].setflags(write=True)

    def test_stale_boolean_or_changed_source_rejected_before_dispatch(self):
        _, pool = self.pool(cache_bytes=80)
        x = np.ones((2, 5))
        pool.predict(x, source_digests=SOURCES, feature_identity=IDENTITY, generation=1)
        for fields in ({"generation": True}, {"generation": 2}, {"feature_identity": "d" * 64},
                       {"top_k": True}, {"top_k": 0}):
            args = {"source_digests": SOURCES, "feature_identity": IDENTITY, "generation": 1, **fields}
            with self.subTest(fields=fields), self.assertRaises(BatchRuntimeError):
                pool.predict(x, **args)
        with self.assertRaises(BatchRuntimeError):
            pool.predict(x * 2, source_digests=SOURCES, feature_identity=IDENTITY, generation=1)
        self.assertEqual(pool.accounting()["dispatch_calls"], 1)

    def test_cache_evicts_under_actual_byte_limit_and_misses_are_explicit(self):
        cache = GlobalFeatureCache(40)
        cache.put("a", np.arange(5))
        cache.put("b", np.arange(5) + 1)
        self.assertIsNone(cache.get("a"))
        self.assertEqual((cache.bytes, cache.evictions), (40, 1))
        entries = GlobalFeatureCache(1000, capacity_entries=1)
        entries.put("a", np.arange(5))
        entries.put("b", np.arange(5))
        self.assertIsNone(entries.get("a"))
        self.assertEqual(entries.bytes, 40)
        _, pool = self.pool(cache_bytes=0)
        with self.assertRaises(BatchRuntimeError):
            pool.predict_cached(SOURCES, feature_identity=IDENTITY, generation=1)

    def test_router_prototypes_are_owned_and_select_expected_cell(self):
        keys = np.array([[1, 0, 0, 0, 0], [0, 1, 0, 0, 0], [0, 0, 1, 0, 0.]])
        _, pool = self.pool(router_keys=keys)
        keys[:] = 0
        out = pool.predict(np.array([[0, 1, 0, 0, 0.]]), source_digests=SOURCES[:1],
                           feature_identity=IDENTITY, generation=1, top_k=1)
        self.assertEqual(out["selected_cell_ids"], [["cell-b"]])
        self.assertEqual(out["route_mode"], "shared_prototype_dot")

    def test_replicated_head_count_does_not_invent_distinct_learning(self):
        head = self.heads("linear")[0]
        pool = BatchedCellRuntime([head] * 64, [f"replica-{i}" for i in range(64)],
                                 ["one-task"] * 64, IDENTITY)
        report = pool.accounting()
        self.assertEqual((report["resident_cells"], report["declared_task_count"],
                          report["unique_parameter_states"]), (64, 1, 1))
        self.assertEqual(report["private_parameter_tensor_bytes"], 64 * head.tensor_bytes)

    def test_identity_bound_artifact_rejects_another_feature_space(self):
        head = self.heads("linear")[0]
        head.feature_identity = "d" * 64
        with self.assertRaisesRegex(BatchRuntimeError, "different feature identity"):
            BatchedCellRuntime([head], ["cell"], ["task"], IDENTITY)


if __name__ == "__main__":
    unittest.main()
