"""Source-only controls; no test starts the numerical candidate."""

import ast
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_candidate_compare import compare, run


class SourceTest(unittest.TestCase):
    def test_parent_is_numerically_cold(self):
        tree = ast.parse(Path(run.__file__).read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        self.assertFalse({name.split(".")[0] for name in imports} & {"numpy", "scipy", "torch"})
        self.assertIn("preexec_fn=_limit", Path(run.__file__).read_text())

    def test_comparator_reuses_archived_oracle(self):
        source = Path(compare.__file__).read_text()
        self.assertIn("oracle_reexecutions\": 0", source)
        self.assertNotIn("dense_oracle", "\n".join(
            node.module or "" for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
        ))
        self.assertEqual(compare.ORACLE_SHA256, "b2a6e204e613fead7c0735b12a335a88d2394c8f4da99cab798133443c55dc18")

    def test_exact_gate_is_not_relaxed(self):
        source = Path(run.__file__).read_text()
        self.assertIn('result["candidate_oracle_bitwise_equal"] is not True', source)
        self.assertNotIn("allclose", Path(compare.__file__).read_text())

    def test_ulp_order(self):
        import struct

        one = struct.pack("<d", 1.0)
        next_one = struct.pack("<Q", struct.unpack("<Q", one)[0] + 1)
        self.assertEqual(abs(compare._ordered_int(one) - compare._ordered_int(next_one)), 1)

    def test_sparse_sink_is_explicitly_two_dimensional(self):
        source = (
            Path(compare.__file__).parents[1]
            / "hcsn_currentstate_n256_sparse_dynamic_v2_intent"
            / "sparse_dynamic.py"
        ).read_text()
        tree = ast.parse(source)
        constructors = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "csr_matrix"
        ]
        self.assertTrue(any(
            isinstance(node.args[0], ast.Tuple)
            and len(node.args[0].elts) == 1
            and isinstance(node.args[0].elts[0], ast.BinOp)
            for node in constructors
            if node.args
        ))


if __name__ == "__main__":
    unittest.main()
