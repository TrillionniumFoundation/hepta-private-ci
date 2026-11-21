"""Tests for the authentic N256 signed-provider adapter review."""

import ast
import struct
import unittest
from pathlib import Path

from .adapter import adapt_lane, review


class SignedAdapterReviewTest(unittest.TestCase):
    def test_small_byte_exact_round_trip(self):
        matrix = struct.pack("<4d", -2.0, 3.0, 0.0, -0.0)
        seed = struct.pack(
            "<10d",
            1.0,
            -1.0,
            0.0,
            -0.0,
            2.0,
            -2.0,
            3.0,
            -3.0,
            4.0,
            -4.0,
        )
        adapted = adapt_lane(matrix, seed, 2)
        self.assertEqual(adapted["review"]["matrix_sparse_coordinates"], 3)
        self.assertTrue(adapted["review"]["matrix_round_trip_byte_equal"])
        self.assertTrue(adapted["review"]["seed_round_trip_byte_equal"])

    def test_authentic_review(self):
        result = review()
        self.assertEqual(result["scope"]["cause_of_6901_red"], "UNKNOWN")
        self.assertEqual(result["work"]["provider_calls"], 0)
        self.assertFalse(result["scope"]["n256_qualified"])

    def test_source_has_no_propagation_kernel(self):
        tree = ast.parse((Path(__file__).parent / "adapter.py").read_text())
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertTrue({"numpy", "scipy", "torch"}.isdisjoint(imports))
        calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        forbidden = {"expm", "expm_multiply", "matrix_exp", "backward", "step"}
        self.assertTrue(forbidden.isdisjoint(calls))


if __name__ == "__main__":
    unittest.main()
