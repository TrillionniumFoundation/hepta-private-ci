"""Behavioral boundaries for actual preference feedback and joint backups."""

import unittest

import numpy as np
import torch

from ...v6.data import Target
from .adapter import Generator, generic_memory, scalar_feedback
from .critic import predict, task_cost


class SemanticBoundaryTests(unittest.TestCase):
    def test_scalar_uses_actual_caption_and_can_remain_unknown(self):
        expected = [2, 7]
        self.assertEqual(scalar_feedback("left 2 right 7 relation less", expected), 1)
        self.assertEqual(scalar_feedback("left 7 right 2 relation greater", expected), -1)
        self.assertEqual(scalar_feedback("left 2 right 7 relation greater", expected), 0)
        self.assertEqual(scalar_feedback("left 3 right 7 relation less", expected), 0)
        self.assertEqual(scalar_feedback("a claimed good answer", expected), 0)
        self.assertEqual(scalar_feedback("left 2 right 2 relation equal", [2, 2]), 1)

    def test_private_target_is_rejected_before_generation(self):
        generator = Generator.__new__(Generator)
        target = Target(torch.zeros(1, 1, 28, 56), torch.zeros(1, 8, dtype=torch.long), torch.zeros(1, 2, dtype=torch.long))
        with self.assertRaises(TypeError):
            generator.deliver(target, 0, "/unused")

    def test_joint_feedback_preserves_terminal_dependence_and_real_refusal(self):
        rows = [
            {"condition": "clean", "feedback": -1, "initial": {"utility": -1.0, "strict_success": 0},
             "alternate": {"utility": 1.0, "strict_success": 1}},
            {"condition": "clean", "feedback": 1, "initial": {"utility": 1.0, "strict_success": 1},
             "alternate": {"utility": -1.0, "strict_success": 0}},
        ]
        heads = {"native_by_feedback": {"-1": {"proposal": True}, "0": {"proposal": False}, "1": {"proposal": False}}}
        active = predict(rows, "clean", "native_numeric", 7, 2, heads, 0)
        expired = predict(rows, "clean", "native_numeric", 6, 2, heads, 0)
        empty_budget = predict(rows, "clean", "native_numeric", 7, 1, heads, 0)
        permuted = predict(rows, "clean", "native_permuted", 7, 2, heads, 0)
        self.assertEqual(active["strict_probability"], 1.0)
        self.assertEqual(expired, {**empty_budget})
        self.assertEqual(expired["strict_probability"], 0.5)
        self.assertEqual(permuted["strict_probability"], 0.5)
        self.assertGreater(expired["moment"], np.exp(-2 * expired["mean_utility"]))
        self.assertAlmostEqual(expired["mean_cost"], (task_cost(True, False) + task_cost(False, False)) / 2)

    def test_same_dimensional_memory_retains_three_distinct_symbols(self):
        values = [generic_memory(symbol) for symbol in (-1, 0, 1)]
        self.assertEqual(len(values[0]) - 1, 10)
        self.assertEqual(np.linalg.matrix_rank(np.asarray(values)), 3)
        coefficient = np.linalg.lstsq(np.asarray(values), np.array([2.0, -0.5, -2.0]), rcond=None)[0]
        self.assertTrue(np.allclose(np.asarray(values) @ coefficient, [2.0, -0.5, -2.0]))


if __name__ == "__main__":
    unittest.main()
