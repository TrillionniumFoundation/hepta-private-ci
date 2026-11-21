"""Tests for the zero-propagation provider compatibility review."""

import ast
import unittest
from pathlib import Path

from .audit import audit


class CompatibilityAuditTest(unittest.TestCase):
    def test_exact_authentic_structure(self):
        result = audit()
        self.assertEqual(
            result["finding"],
            {
                "finite_metzler_augmented_matrices": True,
                "positive_row_sums_present": True,
                "uniformized_transition_l1_norm_above_one": True,
                "signed_seed_channels_present": True,
                "substochastic_sparse_subgenerator_direct_path_compatible": False,
                "signed_non_substochastic_interval_path_required": True,
            },
        )
        self.assertEqual(result["scope"]["cause_of_6901_red"], "UNKNOWN")

    def test_source_has_no_numerical_kernel(self):
        tree = ast.parse((Path(__file__).parent / "audit.py").read_text())
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
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
