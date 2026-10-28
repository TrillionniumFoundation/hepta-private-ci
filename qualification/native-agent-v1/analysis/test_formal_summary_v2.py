"""Retest v2 with the actual gateway serializer as an independent fixture oracle.

No ModelGateway is constructed; importing this module performs no HTTP activity.
Set MODEL_GATEWAY_SOURCE if the qualification source is elsewhere.
"""
import importlib.util
import json
import os
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = load("formal_summary_original", HERE / "formal_summary.py")
V2 = load("formal_summary_v2", HERE / "formal_summary_v2.py")
BASE = load("formal_summary_original_tests", HERE / "test_formal_summary.py")
gateway_override = os.environ.get("MODEL_GATEWAY_SOURCE")
gateway_candidates = [Path(gateway_override)] if gateway_override else [
    HERE.parent / "model_gateway.py",  # Published qualification/native-agent-v1/analysis/ layout.
    HERE.parent / "native_checkout/qualification/native-agent-v1/model_gateway.py",  # Local review layout.
]
gateway_path = next((path for path in gateway_candidates if path.is_file()), None)
if gateway_path is None:
    raise FileNotFoundError("Actual model_gateway.py is required; set MODEL_GATEWAY_SOURCE to its source path")
GATEWAY = load("qualification_actual_gateway", gateway_path)
# The original fixture repeated the audit's sort_keys error. Use the observed
# gateway's actual wire() for both original request and effective capture data.
BASE.SUMMARY = V2
BASE.wire = GATEWAY.wire


class FormalSummaryV2Test(BASE.FormalSummaryTest):
    def test_unsorted_nested_unicode_request_matches_gateway_without_raw_cap(self):
        body = {"model": V2.MODEL,
            "tools": [{"type": "function", "name": "hepta_probe", "description": "实际工具",
                "parameters": {"type": "object", "properties": {"z": {"type": "string"}, "a": {"type": "number"}}}}],
            "input": [{"role": "user", "content": "中文输入"}]}
        record = self.capture("unsorted", 1, body)
        entry = {"case": "unsorted", "call": 1, "record": record}
        old, new = V1.audit_call(entry, self.model_dir), V2.audit_call(entry, self.model_dir)
        self.assertFalse(old["effective_request_hash_verified"])
        self.assertFalse(old["effective_cap_verified_within_256"])
        self.assertTrue(new["request_hash_matches_record"])
        self.assertTrue(new["effective_request_hash_verified"])
        self.assertTrue(new["effective_cap_verified_within_256"])
        self.assertTrue(new["effective_request_bytes_verified_within_65536"])
        self.assertEqual(new["actual_max_output_tokens"], "unknown")
        original = (self.model_dir / "unsorted-model-01.request.json").read_bytes()
        original_body = json.loads(original)
        self.assertNotIn("max_output_tokens", original_body)
        original_body["max_output_tokens"] = 256
        self.assertNotEqual(GATEWAY.wire(original_body), json.dumps(
            original_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
        self.assertEqual(record["effective_bytes"], len(GATEWAY.wire(original_body)))

    def test_existing_cap_replacement_preserves_its_original_position(self):
        body = {"tools": [{"type": "function", "name": "hepta_probe"}],
            "max_output_tokens": 512, "model": V2.MODEL, "input": []}
        record = self.capture("replacement", 1, body)
        new = V2.audit_call({"case": "replacement", "call": 1, "record": record}, self.model_dir)
        self.assertTrue(new["effective_request_hash_verified"])
        self.assertTrue(new["effective_cap_verified_within_256"])
        self.assertEqual(new["actual_max_output_tokens"], 512)
        self.assertFalse(new["requested_cap_within_256"])

    def test_corrupt_effective_record_is_not_silently_accepted(self):
        record = self.capture("bad-hash", 1)
        record["effective_sha256"] = "0" * 64
        new = V2.audit_call({"case": "bad-hash", "call": 1, "record": record}, self.model_dir)
        self.assertFalse(new["effective_request_hash_verified"])
        self.assertFalse(new["effective_cap_verified_within_256"])
        self.assertTrue(new["request_bytes_within_65536"])
        self.assertTrue(new["completed_output_tokens_within_256"])


if __name__ == "__main__":
    unittest.main()
