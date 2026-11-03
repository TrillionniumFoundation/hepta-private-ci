import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

from ndu_receipt_schema import (
    AUTHORITY,
    CANONICALIZATION,
    MODE,
    SCHEMA_ID,
    build_event,
    canonical_json,
    validate_event,
)


ROOT = Path(__file__).resolve().parent


class NDUReceiptSchemaTests(unittest.TestCase):
    def test_golden_vector_round_trip_and_digest(self):
        golden = json.loads((ROOT / "ndu_shadow_event_seed17.json").read_text())
        generated = build_event(17)
        self.assertEqual(golden, generated)
        self.assertEqual(validate_event(golden), golden)
        self.assertEqual(golden["schema_id"], SCHEMA_ID)
        self.assertEqual(golden["protocol"]["mode"], MODE)
        self.assertEqual(golden["protocol"]["authority"], AUTHORITY)
        self.assertEqual(golden["integrity"]["canonicalization"], CANONICALIZATION)

    def test_canonicalization_is_key_order_independent_and_float_stable(self):
        left = {"b": 1.5, "a": {"z": 2.0, "y": [3.0, -0.0]}}
        right = {"a": {"y": [3.0000000000001, 0.0], "z": 2.0}, "b": 1.5000000000001}
        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(canonical_json(left), '{"a":{"y":["3.000000000000","0.000000000000"],"z":"2.000000000000"},"b":"1.500000000000"}')

    def test_tamper_is_rejected_even_when_payload_is_well_formed(self):
        event = build_event(17)
        tampered = copy.deepcopy(event)
        tampered["payload"]["outcome"] += 0.01
        with self.assertRaises(ValueError):
            validate_event(tampered)

        denied = copy.deepcopy(event)
        denied["protocol"]["provider_dispatch"] = True
        with self.assertRaises(ValueError):
            validate_event(denied)

    def test_receipt_semantics_and_cross_process_export(self):
        event = build_event(23)
        payload = event["payload"]
        decision = payload["receipts"]["decision"]
        pending = payload["receipts"]["pending_outcome"]
        observed = payload["receipts"]["observed_outcome"]
        self.assertEqual(set(decision["support"]), {"action", "thinking", "branch", "stop"})
        self.assertEqual(decision["decision_id"], pending["decision_id"])
        self.assertEqual(decision["decision_id"], observed["decision_id"])
        self.assertLess(pending["watermark"], observed["watermark"])
        self.assertIsNone(pending["outcome"])
        self.assertTrue(observed["observed"])

        proc = subprocess.run(
            [sys.executable, "ndu_receipt_schema.py", "--seed", "23"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        external = json.loads(proc.stdout)
        self.assertEqual(external, event)

    def test_schema_manifest_hashes_match_files(self):
        manifest = json.loads((ROOT / "ndu_schema_manifest.json").read_text())
        self.assertEqual(manifest["protocol"]["mode"], MODE)
        schema_item = manifest["schemas"][0]
        vector_item = manifest["golden_vectors"][0]
        schema_hash = hashlib.sha256((ROOT / schema_item["file"]).read_bytes()).hexdigest()
        vector_bytes = (ROOT / vector_item["file"]).read_bytes()
        vector_hash = hashlib.sha256(vector_bytes).hexdigest()
        self.assertEqual(schema_item["sha256"], schema_hash)
        self.assertEqual(vector_item["sha256"], vector_hash)
        golden = json.loads(vector_bytes)
        self.assertEqual(vector_item["event_digest"], golden["integrity"]["event_digest"])
        validate_event(golden)


if __name__ == "__main__":
    unittest.main()
