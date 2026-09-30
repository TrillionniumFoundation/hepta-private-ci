"""Diagnostic fixture tests, never provider or training-rights receipts."""
import copy
import json
import unittest
from teacher_connectivity import inspect_response, strict_json


class TeacherConnectivityTests(unittest.TestCase):
    def setUp(self):
        self.model = "openai/gpt-6-luna"
        self.nonce = "test.opaque.1"
        self.payload = {"schema": "hepta.teacher-connectivity.v1", "nonce": self.nonce,
                        "advisory_only": True, "training_authorized": False}
        self.response = {"status": "ok", "runId": "run.1", "result": {
            "payloads": [{"text": json.dumps(self.payload), "mediaUrl": None}],
            "meta": {"aborted": False, "agentMeta": {
                "provider": "openai", "model": "gpt-6-luna"}}}}

    def inspect(self, response=None, catalog=None):
        return inspect_response(catalog=(catalog or self.model + "\n").encode(),
            response=json.dumps(self.response if response is None else response).encode(),
            diagnostics=b"", expected_model=self.model, nonce=self.nonce)

    def test_connectivity_does_not_grant_training_or_provider_qualification(self):
        result = self.inspect()
        self.assertTrue(result["connectivity_verified"])
        for key in ("provider_qualified", "training_rights_verified", "training_data_admitted",
                    "tool_isolation_verified", "operator_acceptance", "production_activation",
                    "external_effect_qualified"):
            self.assertIs(result[key], False)

    def test_requested_model_absent_is_not_a_fallback_permission(self):
        result = inspect_response(catalog=b"openai/gpt-5.6-luna\n", response=b"",
            diagnostics=b"model override rejected", expected_model=self.model, nonce=self.nonce)
        self.assertEqual(result["status"], "requested_model_not_configured")
        self.assertFalse(result["connectivity_verified"])

    def test_old_model_response_cannot_be_relabelled(self):
        self.response["result"]["meta"]["agentMeta"]["model"] = "gpt-5.6-luna"
        result = self.inspect()
        self.assertEqual(result["status"], "provider_model_mismatch")

    def test_model_self_report_is_not_provider_identity(self):
        self.response["result"]["meta"].pop("agentMeta")
        self.assertEqual(self.inspect()["status"], "provider_identity_unobserved")

    def test_errors_retain_the_gateway_run_for_reconciliation(self):
        result = self.inspect({"ok": False, "error": {"type": "timeout"}, "runId": "run.pending"})
        self.assertEqual(result["status"], "gateway_error_reconcile_before_retry")
        self.assertEqual(result["gateway_run_id"], "run.pending")
        self.assertFalse(result["connectivity_verified"])

    def test_missing_completion_is_not_success(self):
        del self.response["result"]["meta"]["aborted"]
        self.assertEqual(self.inspect()["status"], "completion_not_confirmed")

    def test_partial_and_aborted_responses_are_not_success(self):
        self.response["status"] = "in_flight"
        self.assertEqual(self.inspect()["status"], "gateway_not_terminal")
        self.response["status"] = "ok"
        self.response["result"]["meta"]["aborted"] = True
        self.assertEqual(self.inspect()["status"], "completion_not_confirmed")

    def test_nonce_drift_unknown_fields_and_numeric_flags_reject(self):
        for update in ({"nonce": "other"}, {"extra": "unbound"},
                       {"training_authorized": 0}, {"advisory_only": 1}):
            with self.subTest(update=update):
                value = copy.deepcopy(self.response)
                value["result"]["payloads"][0]["text"] = json.dumps({**self.payload, **update})
                self.assertEqual(self.inspect(value)["status"], "reply_binding_mismatch")

    def test_media_and_multiple_payloads_reject(self):
        self.response["result"]["payloads"][0]["mediaUrl"] = "opaque"
        self.assertEqual(self.inspect()["status"], "unexpected_reply_shape")
        self.response["result"]["payloads"] *= 2
        self.assertEqual(self.inspect()["status"], "unexpected_reply_shape")

    def test_catalog_accepts_namespaced_and_tagged_other_backends(self):
        catalog = self.model + "\nollama/kimi-k2.5:cloud\nollama/owner/model:tag\n"
        self.assertTrue(self.inspect(catalog=catalog)["connectivity_verified"])

    def test_current_catalog_is_required_even_for_an_old_success(self):
        self.assertEqual(self.inspect(catalog="openai/gpt-5.6-luna\n")["status"],
                         "requested_model_not_configured")

    def test_duplicate_nonfinite_and_oversized_json_reject(self):
        for raw in (b'{"ok":true,"ok":false}', b'{"value":NaN}', b" " * 262145):
            with self.subTest(raw=raw[:40]):
                with self.assertRaises(ValueError):
                    strict_json(raw)

    def test_report_does_not_echo_error_or_credentials(self):
        result = inspect_response(catalog=b"openai/gpt-5.6-luna\n", response=b"",
            diagnostics=b"access_token=fixture-secret", expected_model=self.model, nonce=self.nonce)
        self.assertNotIn("fixture-secret", json.dumps(result))
        self.assertNotIn("access_token", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
