"""Tests for the authentic N256 signed resource review."""

import ast
import unittest
from pathlib import Path

from .review import review


class SignedResourceReviewTest(unittest.TestCase):
    def test_authentic_work_ledger_is_fail_closed(self):
        result = review()
        self.assertEqual(result["totals"]["scalar_provider_calls_required"], 10)
        self.assertEqual(result["totals"]["exact_input_conversions"], 11555)
        self.assertEqual(
            result["totals"]["minimum_sparse_product_contributions"], 4822260
        )
        self.assertEqual(
            result["totals"]["maximum_sparse_product_contributions"], 9195520
        )
        self.assertFalse(result["finding"]["resource_gate_closed"])
        self.assertEqual(result["work"]["provider_calls"], 0)
        self.assertFalse(result["scope"]["n256_qualified"])

    def test_source_has_no_provider_or_numerical_call(self):
        tree = ast.parse((Path(__file__).parent / "review.py").read_text())
        calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        forbidden = {
            "non_substochastic_signed_outputs_from_fp64_intervals",
            "expm",
            "expm_multiply",
            "matrix_exp",
            "backward",
            "step",
        }
        self.assertTrue(forbidden.isdisjoint(calls))


if __name__ == "__main__":
    unittest.main()
