import itertools
import unittest

import numpy as np

from v3.capacity_models import (
    allocate_partition,
    coordinate_split,
    fit_partition,
    kmeans_routes,
)
from v3.factor_cell import FactorBank


class CapacityAllocationTests(unittest.TestCase):
    def test_exact_budget_allocation_matches_exhaustive_selection(self):
        rng = np.random.default_rng(8011)
        values = rng.integers(-20, 21, size=(9, 4), dtype=np.int32)
        routes = np.repeat(np.arange(3), 3)
        selection, hidden = coordinate_split(values.shape, 8011)
        self.assertFalse((selection & hidden).any())
        self.assertTrue((selection | hidden).all())
        fitted = fit_partition(values, routes, selection)
        candidates = []
        for choices in itertools.product(*fitted["candidates"]):
            bank = FactorBank(
                routes,
                np.ones(values.shape, dtype=bool),
                tuple(c["block"] for c in choices),
            )
            candidates.append(
                (
                    len(bank.to_bytes()),
                    sum(c["selection_squared_error"] for c in choices),
                )
            )
        for budget in range(20, 300, 7):
            feasible = [(size, score) for size, score in candidates if size <= budget]
            allocated = allocate_partition(fitted, budget)
            if not feasible:
                self.assertIsNone(allocated)
            else:
                bank, receipt = allocated
                best = min(feasible, key=lambda pair: (pair[1], pair[0]))
                self.assertEqual(
                    (len(bank.to_bytes()), receipt["selection_squared_error"]), best
                )

    def test_kmeans_fits_separated_cells_and_handles_duplicate_rows(self):
        values = np.vstack(
            [np.zeros((8, 3), dtype=np.int32), np.full((8, 3), 30, dtype=np.int32)]
        )
        routes, receipt = kmeans_routes(values, 2, 8011)
        self.assertEqual(len(set(routes[:8])), 1)
        self.assertEqual(len(set(routes[8:])), 1)
        self.assertNotEqual(routes[0], routes[-1])
        self.assertGreater(receipt["distance_component_terms"], 0)
        routes, receipt = kmeans_routes(np.zeros((10, 4), dtype=np.int32), 5, 8017)
        self.assertEqual(set(routes.tolist()), set(range(5)))
        self.assertLessEqual(receipt["iterations"], 20)


if __name__ == "__main__":
    unittest.main()
