from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent


class SourceTests(unittest.TestCase):
    def test_request_is_fail_closed_and_zero_numerical(self) -> None:
        request = json.loads((HERE / "REQUEST.json").read_text(encoding="utf-8"))
        self.assertEqual(request["on_mismatch"], "reject_before_numerical_import_or_execution")
        self.assertEqual(request["budget"]["candidate_model_calls"], 0)
        self.assertEqual(request["budget"]["dynamic_steps"], 0)
        self.assertEqual(request["budget"]["dense_expm_actions"], 0)
        self.assertEqual(request["budget"]["torch_calls"], 0)
        self.assertEqual(request["budget"]["optimizer_steps"], 0)

    def test_probe_has_no_numeric_imports_or_candidate_entry(self) -> None:
        source = (HERE / "probe.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(imported.isdisjoint({"numpy", "scipy", "torch"}))
        self.assertNotIn("JointModel", source)
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(called.isdisjoint({"expm", "expm_multiply", "solve_ivp"}))
        forbidden_json_names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id in {"false", "true", "null"}
        }
        self.assertEqual(forbidden_json_names, set())
        self.assertIn('read_text("RECORD")', source)
        self.assertIn("record_text.encode()", source)

    def test_historical_red_and_hold_are_explicit(self) -> None:
        request = json.loads((HERE / "REQUEST.json").read_text(encoding="utf-8"))
        self.assertFalse(request["qualification"])
        self.assertFalse(request["production_adoption"])
        self.assertEqual(request["c2_full_replay_completed_fits"], 0)
        self.assertEqual(request["hpca_status"], "NoUpdate")
        self.assertFalse(request["all_closed"])


if __name__ == "__main__":
    unittest.main()

