"""Toy namespaces exercise identities and the independently defined label laws."""

import unittest

import numpy as np

from .clock_tasks import TASKS, digest, generate_pair, validate_pair


class ClockTaskTests(unittest.TestCase):
    def test_nested_grid_preserves_all_physical_events_and_labels(self):
        for task in TASKS:
            pair = generate_pair("toy/unit/clock", 13, task, "train", 3, 4, 4)
            validate_pair(pair["coarse"], pair["refined"], 4)
            a, b = pair["coarse"], pair["refined"]
            np.testing.assert_array_equal(
                a["write_mask"].sum(1), b["write_mask"].sum(1)
            )
            self.assertEqual(len(set(a["ids"])), 3)
            self.assertNotEqual(digest(a), digest(b))

    def test_hazard_and_filter_labels_obey_external_partition_invariance(self):
        for task in ("held_hazard", "held_filter"):
            pair = generate_pair("toy/unit/clock", 19, task, "dev", 2, 5, 3)
            for data in (pair["coarse"], pair["refined"]):
                x, dt = data["x"], data["dt"]
                if task == "held_hazard":
                    y = -np.expm1(
                        -(
                            (0.15 + np.exp(0.6 * x[:, :, 0] - 0.3 * x[:, :, 1])) * dt
                        ).sum(1)
                    )
                else:
                    y = np.zeros(len(x))
                    for t in range(x.shape[1]):
                        y = (
                            np.exp(-0.8 * dt[:, t]) * y
                            - np.expm1(-0.8 * dt[:, t]) * x[:, t, 0]
                        )
                np.testing.assert_allclose(y, data["y"][:, 0], atol=1e-14, rtol=0)

    def test_split_isolation_and_replay(self):
        a = generate_pair("toy/unit/clock", 7, "event_memory", "train", 3)
        b = generate_pair("toy/unit/clock", 7, "event_memory", "train", 3)
        c = generate_pair("toy/unit/clock", 7, "event_memory", "dev", 3)
        self.assertEqual(digest(a["coarse"]), digest(b["coarse"]))
        self.assertTrue(set(a["coarse"]["ids"]).isdisjoint(c["coarse"]["ids"]))
        self.assertNotEqual(digest(a["coarse"]), digest(c["coarse"]))

    def test_validator_rejects_invented_repeat_write(self):
        pair = generate_pair("toy/unit/clock", 21, "event_memory", "train", 2)
        pair["refined"]["write_mask"][0, 1] = 1
        with self.assertRaises(ValueError):
            validate_pair(pair["coarse"], pair["refined"], 4)


if __name__ == "__main__":
    unittest.main()
