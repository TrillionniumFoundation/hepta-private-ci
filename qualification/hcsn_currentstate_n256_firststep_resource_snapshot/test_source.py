import ast
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent


class ResourceSnapshotSourceTests(unittest.TestCase):
    def test_request_is_read_only_and_keyed(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertFalse(request["n256_numerical_execution_allowed"])
        self.assertFalse(request["resource_admitted"])
        self.assertIsNone(request["allocation_contract"])
        self.assertIsNone(request["calendar_contract"])
        self.assertEqual(
            request["idempotency_key"],
            "hcsn-n256-firststep-resource-snapshot-20261117-c06d-v1",
        )

    def test_source_hash_is_bound(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        observed = hashlib.sha256((ROOT / "snapshot_source.py").read_bytes()).hexdigest()
        self.assertEqual(request["snapshot_source_sha256"], observed)

    def test_future_envelope_is_exact(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertEqual(
            request["future_envelope"],
            {
                "coordinate_denominator": 69728,
                "dynamic_steps": 1,
                "dense_expm_actions": 2,
                "expm_orders": [258, 259],
            },
        )

    def test_source_has_no_hcsn_or_candidate_import(self):
        tree = ast.parse((ROOT / "snapshot_source.py").read_text())
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        self.assertFalse(any(name.startswith("qualification") for name in imported))
        self.assertNotIn("subprocess", imported)

    def test_execution_counts_are_zero(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        for name in (
            "n256_input_reads",
            "n256_serializer_calls",
            "dynamic_steps",
            "matrix_exponential_actions",
            "torch_calls",
            "optimizer_steps",
        ):
            self.assertEqual(request[name], 0)


if __name__ == "__main__":
    unittest.main()
