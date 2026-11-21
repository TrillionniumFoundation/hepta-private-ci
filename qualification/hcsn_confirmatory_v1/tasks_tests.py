"""Independent toy namespaces only; no model or formal holdout is executed."""
import unittest

import numpy as np

from .tasks import TASKS, digest, generate


class TaskTests(unittest.TestCase):
    def test_reproducible_independent_splits_and_clocks(self):
        for task in TASKS:
            args = ("unit-test-only/not-a-campaign", 17, task)
            train = generate(*args, "train", 8)
            again = generate(*args, "train", 8)
            final = generate(*args, "final_clock", 8)
            self.assertEqual(digest(train), digest(again))
            self.assertNotEqual(digest(train), digest(final))
            self.assertFalse(set(train["ids"]) & set(final["ids"]))
            self.assertLess(train["dt"].max(), final["dt"].min())
            self.assertGreater(len(np.unique(train["dt"])), 1)
            self.assertTrue(all(np.isfinite(train[k]).all() for k in ("x", "y", "dt")))

    def test_association_uses_the_queried_past_value(self):
        data = generate("unit-test-only/association", 19, "association", "train", 16)
        x = data["x"]
        key = np.sign(x[:, 0, 0] * x[:, 0, 1])
        expected = np.where(key == x[:, -1, 3], x[:, 0, 0], x[:, 1, 0])
        np.testing.assert_array_equal(expected, data["y"][:, 0])
        self.assertTrue(np.all(x[:, -1, :3] == 0))


if __name__ == "__main__":
    unittest.main()

