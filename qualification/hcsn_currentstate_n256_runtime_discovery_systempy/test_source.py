import ast
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent


class RuntimeDiscoverySourceTests(unittest.TestCase):
    def test_request_is_zero_model_and_keyed(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertEqual(request["executable"], "/usr/bin/python3")
        self.assertEqual(
            request["idempotency_key"],
            "hcsn-n256-runtime-discovery-systempy-20261117-c06d-v1",
        )
        self.assertFalse(request["imports_candidate_modules"])
        self.assertFalse(request["mutates_runtime"])
        self.assertFalse(request["runtime_admitted"])
        self.assertFalse(request["resource_admitted"])
        self.assertEqual(
            request["launch_contract"],
            {
                "args": ["-"],
                "cpu_quota_percent": 100,
                "environment": {},
                "memory_max_bytes": 268435456,
                "nice": 10,
                "timeout_seconds": 30,
            },
        )

    def test_source_hash_is_bound(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        observed = hashlib.sha256((ROOT / "inventory_source.py").read_bytes()).hexdigest()
        self.assertEqual(request["inventory_source_sha256"], observed)

    def test_candidate_set_is_exact(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertEqual(request["candidate_distributions"], ["numpy", "scipy"])

    def test_source_does_not_import_candidates_or_execution_modules(self):
        tree = ast.parse((ROOT / "inventory_source.py").read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertFalse(imported & {"numpy", "scipy", "subprocess", "torch"})
        self.assertFalse(any(name.startswith("qualification") for name in imported))

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
