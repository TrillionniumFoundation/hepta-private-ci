import ast
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class SourceTests(unittest.TestCase):
    def test_one_attempt_and_strict_scope(self):
        request = json.loads((HERE / "REQUEST.json").read_text())
        self.assertEqual(request["maximum_attempts"], 1)
        self.assertEqual(request["historical_numerical_red"]["mismatches"], 665)
        self.assertEqual(request["historical_numerical_red"]["denominator"], 69728)
        self.assertFalse(request["pass_gate"]["tolerance_or_ulp_rescue_allowed"])
        self.assertFalse(request["all_closed"])

    def test_parent_has_no_numerical_import(self):
        for name in ("launcher.py", "resource_guard.py"):
            tree = ast.parse((HERE / name).read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertTrue(imported.isdisjoint({"numpy", "scipy", "torch"}))

    def test_exact_oracle_runtime_identity(self):
        source = (HERE / "resource_guard.py").read_text()
        self.assertIn("(3, 12, 3)", source)
        self.assertIn("ubuntu\", \"24.04", source)
        self.assertIn('distribution.read_text("RECORD").encode()', source)
        self.assertIn("2ce74da59bd24c1301a77e90b94abfe52bc14d54c0f79f565665b5a59d62734b", source)
        self.assertIn("e56c4bae4706cb2932b476f0747869a3173bf3ca", source)

    def test_bounded_child_and_no_retry(self):
        source = (HERE / "launcher.py").read_text()
        self.assertIn("preexec_fn=child_limits", source)
        self.assertIn("timeout=600", source)
        self.assertNotIn("retry", source.lower())

    def test_frozen_child_and_audit_hashes(self):
        freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
        self.assertEqual(freeze["reused_source_sha256"]["child.py"], "c79068da9c52dc7e9976692a25594959995cf155132ee024392ac13987d1de64")
        self.assertEqual(freeze["reused_source_sha256"]["audit.py"], "f620e9d613bd0a8e7779ccfbd7faf357c3bf534bb6050b1cab0a0d9032c9d83f")


if __name__ == "__main__":
    unittest.main()

