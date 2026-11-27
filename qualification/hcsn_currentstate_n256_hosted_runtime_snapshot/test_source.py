import ast
import base64
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
REPO = ROOT.parents[1]
WORKFLOW = REPO / ".github/workflows/hcsn-currentstate-n256-hosted-runtime-snapshot.yml"


class HostedRuntimeSnapshotSourceTests(unittest.TestCase):
    def test_request_is_zero_model_and_preserves_failures(self):
        request = json.loads((ROOT / "REQUEST_V2.json").read_text())
        self.assertFalse(request["n256_numerical_execution_allowed"])
        self.assertFalse(request["runtime_admitted"])
        self.assertFalse(request["resource_admitted"])
        self.assertEqual(len(request["prior_desktop_failures_preserved"]), 3)
        self.assertEqual(request["prior_hosted_failures_preserved"], [44252369558])
        terminal = json.loads((ROOT / "evidence/attempt001/TERMINAL.json").read_text())
        self.assertEqual(terminal["workflow_conclusion"], "failure")
        self.assertEqual(
            terminal["job_log_sha256"],
            hashlib.sha256(
                base64.b64decode(
                    (ROOT / "evidence/attempt001/JOB_LOG.txt.b64").read_bytes()
                )
            ).hexdigest(),
        )
        for name in (
            "n256_input_reads",
            "n256_serializer_calls",
            "dynamic_steps",
            "matrix_exponential_actions",
            "torch_calls",
            "optimizer_steps",
        ):
            self.assertEqual(request[name], 0)

    def test_runtime_versions_are_exact(self):
        request = json.loads((ROOT / "REQUEST_V2.json").read_text())
        self.assertEqual(request["python_version"], "3.12.3")
        self.assertEqual(
            (ROOT / "requirements.txt").read_text().splitlines(),
            ["numpy==2.3.5", "scipy==1.17.0"],
        )
        self.assertTrue(request["binary_wheels_only"])

    def test_capture_only_calls_frozen_observer(self):
        tree = ast.parse((ROOT / "capture.py").read_text())
        imports = set()
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
            elif isinstance(node, ast.Call):
                calls.append(ast.unparse(node.func))
        self.assertFalse(imports & {"numpy", "scipy", "torch", "subprocess"})
        self.assertEqual(calls.count("snapshot_source.observe"), 1)
        self.assertFalse(any("expm" in name.lower() for name in calls))

    def test_workflow_is_one_observation_and_artifact(self):
        text = WORKFLOW.read_text()
        self.assertIn("python-version: \"3.12.3\"", text)
        self.assertIn("--only-binary=:all:", text)
        self.assertEqual(
            text.count(
                "python -m qualification.hcsn_currentstate_n256_hosted_runtime_snapshot.capture"
            ),
            1,
        )
        self.assertIn("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", text)
        for forbidden in ("N256_STATE", "dense_oracle", "torch", "optimizer"):
            self.assertNotIn(forbidden, text)

    def test_request_hashes_bind_execution_sources(self):
        request = json.loads((ROOT / "REQUEST_V2.json").read_text())
        observed = {
            "capture_sha256": hashlib.sha256((ROOT / "capture.py").read_bytes()).hexdigest(),
            "snapshot_source_sha256": hashlib.sha256(
                (
                    REPO
                    / "qualification/hcsn_currentstate_n256_firststep_resource_snapshot/snapshot_source.py"
                ).read_bytes()
            ).hexdigest(),
        }
        self.assertEqual(
            {name: request[name] for name in observed},
            observed,
        )


if __name__ == "__main__":
    unittest.main()
