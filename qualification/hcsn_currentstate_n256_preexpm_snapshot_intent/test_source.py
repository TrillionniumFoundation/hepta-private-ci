"""Static controls for the pre-expm input snapshot intent."""

import ast
import unittest
from pathlib import Path


HERE = Path(__file__).parent


class SourceTest(unittest.TestCase):
    def test_snapshot_has_no_exponential_or_training_call(self):
        tree = ast.parse((HERE / "snapshot.py").read_text())
        called = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        self.assertTrue({"expm", "matrix_exp", "backward", "step"}.isdisjoint(called))

    def test_numpy_is_not_imported_before_host_snapshot(self):
        source = (HERE / "snapshot.py").read_text()
        prefix = source[: source.index("    import numpy as np")]
        self.assertNotIn("import numpy", prefix)
        self.assertIn("host = _host_before_numpy()", prefix)

    def test_complete_freeze(self):
        from qualification.hcsn_currentstate_n256_preexpm_snapshot_intent.verify_source import (
            verify,
        )

        self.assertEqual(
            verify(),
            {
                "status": "SOURCE_FROZEN",
                "frozen_source_files": 6,
                "bound_dependency_files": 5,
                "stream_action_ast_equal": True,
                "source_branch_execution_count": 0,
                "all_closed": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
