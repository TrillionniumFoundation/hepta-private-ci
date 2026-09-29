import json
import unittest
from teacher_connectivity import inspect_response


class TeacherEntitlementTests(unittest.TestCase):
    def inspect(self, model="gpt-6-luna", status=400, message=None):
        error = {"type":"error", "status":status, "error":{"type":"invalid_request_error", "message":
            message or f"The '{model}' model is not supported when using Codex with a ChatGPT account."}}
        diagnostic = ('embedded run failover decision: runId=abc-123 stage=prompt rawError=' + json.dumps(error)).encode()
        return inspect_response(catalog=b"openai/gpt-6-luna\n", response=b"", diagnostics=diagnostic,
                                expected_model="openai/gpt-6-luna", nonce="test-nonce")

    def test_structured_upstream_rejection_not_confused_with_missing_catalog(self):
        report = self.inspect()
        self.assertEqual(report['status'], 'requested_model_unsupported_for_auth_route')
        self.assertEqual(report['upstream_http_status'], 400)
        self.assertEqual(report['gateway_run_id'], 'abc-123')

    def test_other_model_does_not_supply_requested_model_evidence(self):
        self.assertEqual(self.inspect(model='gpt-other')['status'], 'response_unavailable')

    def test_timeout_is_not_an_entitlement_rejection(self):
        self.assertEqual(self.inspect(status=504)['status'], 'response_unavailable')

    def test_unstructured_prose_is_not_upstream_evidence(self):
        value = inspect_response(catalog=b'openai/gpt-6-luna\n', response=b'',
            diagnostics=b'gpt-6-luna unsupported', expected_model='openai/gpt-6-luna', nonce='probe')
        self.assertEqual(value['status'], 'response_unavailable')

    def test_rejection_never_grants_training_or_provider_authority(self):
        value = self.inspect()
        for key in ('connectivity_verified','provider_qualified','training_rights_verified',
                    'training_data_admitted','tool_isolation_verified','operator_acceptance','production_activation'):
            self.assertIs(value[key], False)


if __name__ == '__main__': unittest.main()
