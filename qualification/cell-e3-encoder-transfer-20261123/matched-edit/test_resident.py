"""Numerical equivalence, failed-update isolation and bounded cache behavior."""
import unittest

import numpy as np

from resident import FeatureCache, RecursiveRidge, direct


class ResidentTests(unittest.TestCase):
    def test_recursive_matches_same_objective_with_correlated_rows(self):
        rng = np.random.default_rng(443)
        x, y = rng.normal(size=(72, 113)), rng.normal(size=72)
        x[30:35] = x[:5]  # deliberately rank deficient, regularizer is unchanged
        state = RecursiveRidge(x[:16], y[:16], max_rows=72)
        for stop in range(24, 73, 8):
            got = state.append(x[stop - 8:stop], y[stop - 8:stop])
            want = direct(x[:stop], y[:stop])
            np.testing.assert_allclose(got, want, atol=1e-10, rtol=1e-10)
            np.testing.assert_allclose(x[:stop].T @ (x[:stop] @ got - y[:stop]) + .2 * got,
                                       0, atol=1e-9)

    def test_bad_append_keeps_previous_candidate(self):
        state = RecursiveRidge(np.eye(3), np.ones(3), max_rows=4)
        before = (state.x.copy(), state.y.copy(), state.weights.copy(), state.inverse.copy())
        for x, y in ((np.ones((2, 3)), np.ones(2)),
                     (np.ones((1, 2)), np.ones(1)), (np.full((1, 3), np.nan), np.ones(1))):
            with self.assertRaises(ValueError):
                state.append(x, y)
            for a, b in zip(before, (state.x, state.y, state.weights, state.inverse), strict=True):
                np.testing.assert_array_equal(a, b)

    def test_cache_deduplicates_inputs_without_leaking_mutable_arrays(self):
        class Encoder:
            def __init__(self):
                self.count = 0

            def features(self, rows):
                self.count += len(rows)
                a = np.array([[len(r["query"])] for r in rows], dtype=float)
                return a, a + 1, a[:, 0] + 2

        model = Encoder()
        cache = FeatureCache(model, "frozen-test-encoder", capacity=2)
        row = {"query": "one", "candidates": ["A", "B"], "label": 0}
        first = cache.features([row, dict(row, label=1)])
        first[0][:] = -99
        np.testing.assert_array_equal(cache.features([row])[0], [[3.]])
        self.assertEqual(model.count, 1)
        cache.features([dict(row, query="two"), dict(row, query="three")])
        self.assertEqual(len(cache.entries), 2)
        cache.features([row])
        self.assertEqual(model.count, 4)


if __name__ == "__main__":
    unittest.main()
