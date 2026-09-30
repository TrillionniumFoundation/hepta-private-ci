"""Retained-observation fixtures; no provider call or training-rights approval."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from teacher_connectivity import inspect_response


def response():
    payload = {"schema": "hepta.teacher-connectivity.v1", "nonce": "fixture-nonce",
               "advisory_only": True, "training_authorized": False}
    return {"status": "ok", "runId": "fixture-run", "ok": True, "result": {
        "payloads": [{"text": json.dumps(payload)}],
        "meta": {"aborted": False, "agentMeta": {"provider": "openai", "model": "gpt-6-luna"}}}}


def inspect(value):
    return inspect_response(catalog=b"openai/gpt-6-luna\n", response=json.dumps(value).encode(),
                            diagnostics=b"", expected_model="openai/gpt-6-luna", nonce="fixture-nonce")


class TeacherConnectivityBoundaryTests(unittest.TestCase):
    def assert_rejected(self, value, status):
        result = inspect(value)
        self.assertEqual(result["status"], status)
        self.assertEqual(result["gateway_run_id"], "fixture-run")
        for field in ("connectivity_verified", "provider_qualified", "training_rights_verified",
                      "training_data_admitted", "tool_isolation_verified", "operator_acceptance",
                      "production_activation", "external_effect_qualified"):
            self.assertIs(result[field], False)

    def test_outer_ok_requires_an_actual_boolean_when_present(self):
        for flag in (0, 1, 0., 1., None, "true", "false", [], {}):
            with self.subTest(flag=flag):
                value = response()
                value["ok"] = flag
                self.assert_rejected(value, "invalid_gateway_flag")

    def test_inner_ok_requires_an_actual_boolean_when_present(self):
        for flag in (0, 1, 0., 1., None, "true", "false", [], {}):
            with self.subTest(flag=flag):
                value = response()
                value["result"]["ok"] = flag
                self.assert_rejected(value, "invalid_gateway_flag")

    def test_outer_success_cannot_override_inner_denial(self):
        value = response()
        value["result"]["ok"] = False
        self.assert_rejected(value, "gateway_error_reconcile_before_retry")

    def test_outer_success_cannot_override_inner_nonterminal_status(self):
        for status in ("running", "in_flight", "failed", "cancelled", 0, False, [], {}):
            with self.subTest(status=status):
                value = response()
                value["result"]["status"] = status
                self.assert_rejected(value, "gateway_not_terminal")

    def test_payload_is_error_requires_absent_or_literal_false(self):
        for flag in (0, 0., None, 1, True, "false", [], {}):
            with self.subTest(flag=flag):
                value = response()
                value["result"]["payloads"][0]["isError"] = flag
                self.assert_rejected(value, "unexpected_reply_shape")
        value = response()
        value["result"]["payloads"][0]["isError"] = False
        self.assertIs(inspect(value)["connectivity_verified"], True)

    def test_missing_optional_flags_and_explicit_success_remain_supported(self):
        value = response()
        del value["ok"]
        self.assertIs(inspect(value)["connectivity_verified"], True)
        value["result"].update(ok=True, status="completed")
        self.assertIs(inspect(value)["connectivity_verified"], True)
        direct = value["result"]
        direct["runId"] = "fixture-run"
        self.assertIs(inspect(direct)["connectivity_verified"], True)

    def test_success_never_qualifies_a_provider_or_training_rights(self):
        result = inspect(response())
        for field in ("provider_qualified", "training_rights_verified", "training_data_admitted",
                      "tool_isolation_verified", "operator_acceptance", "production_activation",
                      "external_effect_qualified"):
            self.assertIs(result[field], False)

    def test_cli_retains_failure_and_cannot_overwrite_evidence(self):
        value = response()
        value["ok"] = 0
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            encoded = json.dumps(value).encode()
            (root / "response.json").write_bytes(encoded)
            (root / "catalog.txt").write_bytes(b"openai/gpt-6-luna\n")
            (root / "diagnostics.txt").write_bytes(b"fixture-secret-not-for-report")
            command = [sys.executable, str(Path(__file__).with_name("teacher_connectivity.py")),
                       "--catalog", str(root / "catalog.txt"), "--response", str(root / "response.json"),
                       "--diagnostics", str(root / "diagnostics.txt"), "--expected-model", "openai/gpt-6-luna",
                       "--nonce", "fixture-nonce", "--output", str(root / "report.json")]
            child = subprocess.run(command, capture_output=True, timeout=10, check=False)
            self.assertEqual(child.returncode, 2, child.stderr.decode())
            saved = (root / "report.json").read_bytes()
            report = json.loads(saved)
            self.assertEqual(report["status"], "invalid_gateway_flag")
            self.assertEqual(report["response_sha256"], hashlib.sha256(encoded).hexdigest())
            self.assertNotIn(b"fixture-secret-not-for-report", saved)
            second = subprocess.run(command, capture_output=True, timeout=10, check=False)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual((root / "report.json").read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
