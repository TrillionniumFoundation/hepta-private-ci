"""Behavioral checks for causal memory, matching, overwrite and abstention."""

import unittest

import numpy as np

from .memory_probe import DeltaMemory, base_content, expand_content, exact_recall


class MemoryContracts(unittest.TestCase):
    def test_insertions_preserve_binding_identity_and_physical_times(self):
        for task in ("selective_copy", "mqar"):
            base = base_content(task, 17, 610031)
            short = expand_content(task, *base, 32, 3.2, 810)
            for length in (128, 512):
                long = expand_content(task, *base, length, 3.2, 810)
                np.testing.assert_array_equal(long["x"][:, long["mapping"]], short["x"])
                np.testing.assert_array_equal(long["gold"], short["gold"])
                np.testing.assert_allclose(long["released"][:, long["mapping"]], short["released"], atol=1e-12)
                np.testing.assert_array_equal(exact_recall(task, long["x"])[0].argmax(-1), long["gold"])

    def test_query_order_follows_address_instead_of_write_order(self):
        values = expand_content("mqar", *base_content("mqar", 17, 620031), 128, 12.8, 811)
        values["x"][:, -4:] = values["x"][:, -4:][:, [2, 0, 3, 1]]
        expected = values["gold"][:, [2, 0, 3, 1]]
        np.testing.assert_array_equal(exact_recall("mqar", values["x"])[0].argmax(-1), expected)

    def test_duplicate_keys_replace_old_content_without_other_key_collision(self):
        memory = DeltaMemory(8)
        keys = np.eye(8, dtype=np.float32)
        for key in range(8):
            self.assertIsNone(memory.step(keys[key]))
            memory.step(keys[key], keys[(key + 2) % 8])
        before = memory.weights.copy()
        memory.step(keys[3], keys[7])
        expected = before.copy()
        expected[3] = keys[7]
        np.testing.assert_array_equal(memory.weights, expected)
        for key in range(8):
            np.testing.assert_array_equal(memory.step(keys[key]), expected[key])
        self.assertEqual(memory.state_bytes, 8 * 8 * 4 + 8)

    def test_task_level_overwrite_changes_all_matching_future_queries(self):
        values = expand_content("mqar", *base_content("mqar", 17, 630031), 128, 12.8, 812)
        expected = values["gold"].copy()
        for row, sequence in enumerate(values["x"]):
            first = np.flatnonzero(sequence[:, 16])[0]
            key, old = np.argmax(sequence[first, :8]), np.argmax(sequence[first, 8:16])
            new = (old + 1) % 8
            sequence[-5] = 0
            sequence[-5, [key, 8 + new, 16]] = 1
            expected[row, sequence[-4:, key] > 0] = new
        np.testing.assert_array_equal(exact_recall("mqar", values["x"])[0].argmax(-1), expected)

    def test_future_write_cannot_change_a_completed_read(self):
        memory = DeltaMemory(8)
        keys = np.eye(8, dtype=np.float32)
        memory.step(keys[2], keys[3])
        read_before = memory.step(keys[2])
        memory.step(keys[2], keys[7])
        np.testing.assert_array_equal(read_before, keys[3])
        np.testing.assert_array_equal(memory.step(keys[2]), keys[7])

    def test_ambiguous_address_is_rejected_without_mutation(self):
        memory = DeltaMemory(8)
        before = memory.weights.copy()
        with self.assertRaises(ValueError):
            memory.step(np.array([1, 1, 0, 0, 0, 0, 0, 0]), np.eye(8)[0])
        np.testing.assert_array_equal(memory.weights, before)


if __name__ == "__main__":
    unittest.main()
