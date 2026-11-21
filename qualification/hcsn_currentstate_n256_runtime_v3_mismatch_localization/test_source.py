import ast
import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


class SourceTests(unittest.TestCase):
    def test_request_preserves_red_and_scope(self):
        value = json.loads((HERE / "REQUEST.json").read_text())
        self.assertEqual(value["maximum_diagnostic_executions"], 1)
        self.assertEqual(value["expected_bitwise_mismatches"], 665)
        self.assertEqual(value["expected_coordinate_comparisons"], 69728)
        self.assertFalse(value["qualification"])
        self.assertFalse(value["all_closed"])

    def test_zero_numerical_work_contract(self):
        value = json.loads((HERE / "REQUEST.json").read_text())
        for key in ("model_calls", "dynamic_steps", "dense_expm_actions", "sparse_expm_actions", "oracle_reexecutions", "torch_calls", "optimizer_steps"):
            self.assertEqual(value[key], 0)

    def test_diagnostic_uses_standard_library_only(self):
        tree = ast.parse((HERE / "diagnose.py").read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        self.assertFalse(any(name.split(".")[0] in {"numpy", "scipy", "torch"} for name in imports))

    def test_no_tolerance_or_execution_rescue(self):
        source = (HERE / "diagnose.py").read_text()
        for forbidden in ("allclose", "isclose", "expm(", "optimizer.step", "torch."):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
