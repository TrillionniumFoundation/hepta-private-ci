import ast
import json
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_dense_compatible_firststep_intent import candidate


HERE = Path(__file__).resolve().parent
SOURCE = (HERE / "candidate.py").read_text()
TREE = ast.parse(SOURCE)


class SourceIntentTests(unittest.TestCase):
    def test_request_denies_execution_and_preserves_sparse_red(self):
        request = json.loads((HERE / "REQUEST.json").read_text())
        self.assertFalse(request["future_attempt"]["execution_allowed"])
        self.assertIsNone(request["future_attempt"]["unique_execution_key"])
        self.assertEqual(request["sparse_red_preserved"]["bitwise_mismatch_coordinates"], 1291)
        self.assertFalse(request["all_closed"])

    def test_source_stage_is_zero_work(self):
        request = json.loads((HERE / "REQUEST.json").read_text())
        self.assertEqual(set(request["source_stage_counts"].values()), {0})

    def test_exact_boundary_guard_rejects_mutation(self):
        reference = b"reference"
        original = candidate.BOUNDARY_SHA256
        try:
            candidate.BOUNDARY_SHA256 = candidate._sha_bytes(reference)
            candidate._require_exact_bytes(reference, reference)
            with self.assertRaisesRegex(ValueError, "bitwise exact"):
                candidate._require_exact_bytes(reference, reference[:-1] + b"X")
        finally:
            candidate.BOUNDARY_SHA256 = original

    def test_no_sparse_or_tolerance_rescue(self):
        self.assertNotIn("expm_multiply", SOURCE)
        self.assertNotIn("allclose", SOURCE)
        self.assertNotIn("isclose", SOURCE)
        imports = [node for node in ast.walk(TREE) if isinstance(node, (ast.Import, ast.ImportFrom))]
        rendered = "\n".join(ast.unparse(node) for node in imports)
        self.assertIn("from scipy.linalg import expm", rendered)

    def test_numerical_import_is_deferred(self):
        top_imports = [node for node in TREE.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        rendered = "\n".join(ast.unparse(node) for node in top_imports)
        self.assertNotIn("numpy", rendered)
        self.assertNotIn("scipy", rendered)

    def test_two_dense_actions_and_two_toctou_hashes(self):
        function = next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "_candidate_envelope")
        calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
        names = [ast.unparse(node.func) for node in calls]
        self.assertEqual(names.count("_stream_action"), 2)
        self.assertEqual(names.count("_sha_bytes"), 2)

    def test_execution_interface_publishes_rebuilt_boundary(self):
        function = next(
            node for node in TREE.body
            if isinstance(node, ast.FunctionDef) and node.name == "execute"
        )
        arguments = [item.arg for item in function.args.args]
        self.assertEqual(
            arguments,
            ["root", "boundary_zip", "oracle_zip", "rebuilt_boundary_path", "output_path"],
        )
        calls = [ast.unparse(node) for node in ast.walk(function) if isinstance(node, ast.Call)]
        self.assertTrue(any(call.startswith("_publish_bytes(rebuilt_boundary_path") for call in calls))


if __name__ == "__main__":
    unittest.main()
