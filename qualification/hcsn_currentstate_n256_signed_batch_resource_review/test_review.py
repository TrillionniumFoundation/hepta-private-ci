"""Tests for the authentic-input signed batch resource review."""

import ast
import unittest
from pathlib import Path

from .review import review


class SignedBatchResourceReviewTest(unittest.TestCase):
    def test_shared_parse_ledger_is_exact_and_fail_closed(self):
        result = review()
        self.assertEqual(result["comparison"]["scalar_exact_input_conversions"], 11555)
        self.assertEqual(
            result["comparison"]["batch_exact_input_conversions_if_admitted"],
            4379,
        )
        self.assertEqual(
            result["comparison"]["exact_input_conversion_reduction"], 7176
        )
        self.assertEqual(result["comparison"]["reduction_fraction"], "7176/11555")
        self.assertEqual(
            result["recurrence_work_if_admitted"][
                "maximum_sparse_product_contributions"
            ],
            9195520,
        )
        self.assertFalse(result["finding"]["authentic_execution_admitted"])
        self.assertEqual(result["work"]["authentic_batch_provider_calls"], 0)
        self.assertFalse(result["scope"]["n256_qualified"])

    def test_review_source_has_no_provider_or_recurrence_call(self):
        tree = ast.parse((Path(__file__).parent / "review.py").read_text())
        calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        forbidden = {
            "non_substochastic_signed_batch_outputs_from_fp64_intervals",
            "non_substochastic_signed_outputs_from_fp64_intervals",
            "_outputs_from_parsed",
            "_row_action",
            "expm",
            "expm_multiply",
            "matrix_exp",
            "backward",
            "step",
        }
        self.assertTrue(forbidden.isdisjoint(calls))


if __name__ == "__main__":
    unittest.main()
