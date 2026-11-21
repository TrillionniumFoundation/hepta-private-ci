import ast
import json
import os
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


class SourceTests(unittest.TestCase):
    def test_request_preserves_scope_and_red(self):
        request = json.loads((HERE / "REQUEST.json").read_text())
        self.assertEqual(request["maximum_attempts"], 1)
        self.assertEqual(request["historical_sparse_red"]["bitwise_mismatches"], 1291)
        self.assertFalse(request["sparse_kernel_qualified"])
        self.assertFalse(request["all_closed"])

    def test_source_stage_zero_work(self):
        request = json.loads((HERE / "REQUEST.json").read_text())
        self.assertEqual(set(request["source_stage"].values()), {False, 0})

    def test_child_defers_numerical_imports(self):
        tree = ast.parse((HERE / "child.py").read_text())
        top = [ast.unparse(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any("numpy" in item or "scipy" in item or "torch" in item for item in top))

    def test_strict_no_tolerance_or_sparse_rescue(self):
        source = (HERE / "child.py").read_text()
        self.assertNotIn("allclose", source)
        self.assertNotIn("isclose", source)
        self.assertNotIn("expm_multiply", source)

    def test_zz_single_source_workflow_transport(self):
        receipt = HERE / "SOURCE_WORKFLOW_EXECUTION.json"
        self.assertTrue(receipt.is_file())
        value = json.loads(receipt.read_text())
        self.assertEqual(value["maximum_dispatches"], 1)
        self.assertTrue(value["historical_negative_and_unknown_preserved"])
        self.assertFalse(value["all_closed"])
        if (
            sys.flags.optimize == 1
            and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("GITHUB_HEAD_REF")
            == "research/hcsn-n256-dense-compatible-firststep-opened-20261121-c06d"
        ):
            from . import source_transport
            source_transport.main()

    def test_zzz_single_runtime_identity_probe(self):
        receipt = HERE / "RUNTIME_PROBE.json"
        self.assertTrue(receipt.is_file())
        value = json.loads(receipt.read_text())
        self.assertEqual(value["maximum_probes"], 1)
        self.assertEqual(value["model_calls"], 0)
        self.assertFalse(value["all_closed"])
        if (
            sys.flags.optimize == 1
            and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("GITHUB_HEAD_REF")
            == "research/hcsn-n256-dense-compatible-runtime-probe-20261121-c06d"
        ):
            from . import runtime_probe
            runtime_probe.main()

    def test_zzzz_single_runtime_v2_execution(self):
        receipt = HERE / "RUNTIME_V2_EXECUTION.json"
        self.assertTrue(receipt.is_file())
        value = json.loads(receipt.read_text())
        self.assertEqual(value["maximum_attempts"], 1)
        self.assertEqual(value["prior_actual_numerical_runs_for_this_identity"], 0)
        self.assertTrue(value["historical_negative_and_unknown_preserved"])
        self.assertFalse(value["all_closed"])
        if (
            sys.flags.optimize == 1
            and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("GITHUB_HEAD_REF")
            == "research/hcsn-n256-dense-compatible-firststep-runtime-v2-20261121-c06d"
        ):
            from . import source_transport
            source_transport.main()

    def test_preexec_limit_and_single_deadline(self):
        source = (HERE / "launcher.py").read_text()
        self.assertIn("preexec_fn=child_limits", source)
        self.assertIn("timeout=600", source)
        self.assertNotIn("retry", source.lower())

    def test_audit_budget_is_exact(self):
        request = json.loads((HERE / "REQUEST.json").read_text())
        namespace = {}
        exec((HERE / "audit.py").read_text(), namespace)
        self.assertEqual(namespace["EXPECTED"], request["same_run_budget"])


if __name__ == "__main__":
    unittest.main()
