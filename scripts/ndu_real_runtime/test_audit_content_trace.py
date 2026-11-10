"""Manufactured legacy artifacts exercise link diagnosis, not scientific benefit."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .audit_content_trace import audit


class LegacyTraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root, self.pins = Path(self.temp.name), {}
        self.evaluator = "e" * 64
        self.put(
            "trajectory.json",
            {
                "steps": [
                    {
                        "step": 0,
                        "case_id": "case",
                        "action": {
                            "action": "WRITE_TEXT",
                            "arguments": {"text": "wrong"},
                        },
                        "candidate_metadata": [{"text": "right"}, {"text": "wrong"}],
                    }
                ]
            },
        )
        self.put(
            "reference.json",
            {"case_id": "case", "field": "company", "expected_text": "right"},
        )
        for i, text in enumerate((None, "wrong")):
            self.put(
                f"delivery-{i:02d}/delivery.json",
                {"schema": "ndu.real.delivery.v1", "case_id": "case", "text": text},
            )
            self.put(
                f"delivery-{i:02d}/evaluation.json",
                {
                    "schema": "ndu.real.independent-evaluation.v1",
                    "case_id": "case",
                    "evaluator_source_sha256": self.evaluator,
                    "text_quality": 0.0,
                    "reference_sha256": self.pins["reference.json"],
                    "delivery_sha256": self.pins[f"delivery-{i:02d}/delivery.json"],
                },
            )

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        self.pins[name] = hashlib.sha256(raw).hexdigest()

    def run_audit(self, reference="reference.json"):
        return audit(
            self.root, self.pins, evaluator_sha256=self.evaluator, reference=reference
        )

    def test_nonmatching_candidate_reaches_scorer_without_claiming_selection(self):
        report = self.run_audit()
        row = report["write_text"][0]
        self.assertTrue(row["action_text_reached_delivery"])
        self.assertTrue(row["evaluator_received_delivery_bytes"])
        self.assertTrue(row["normalized_reference_candidate_available"])
        self.assertFalse(row["delivered_text_matches_reference"])
        self.assertTrue(row["evaluator_text_score_agrees"])
        self.assertFalse(report["selection_root_cause_established"])
        self.assertNotIn('"wrong"', json.dumps(report))
        self.assertNotIn('"right"', json.dumps(report))

    def test_delivery_mismatch_and_wrong_scorer_input_are_separate(self):
        self.put(
            "delivery-01/delivery.json",
            {"schema": "ndu.real.delivery.v1", "case_id": "case", "text": "right"},
        )
        row = self.run_audit()["write_text"][0]
        self.assertFalse(row["action_text_reached_delivery"])
        self.assertFalse(row["evaluator_received_delivery_bytes"])
        self.assertFalse(row["evaluator_text_score_agrees"])

    def test_external_pins_reject_tampering(self):
        (self.root / "trajectory.json").write_text('{"steps": []}')
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.run_audit()

    def test_reference_omission_preserves_unknown(self):
        row = self.run_audit(None)["write_text"][0]
        self.assertIsNone(row["normalized_reference_candidate_available"])
        self.assertIsNone(row["delivered_text_matches_reference"])

    def test_wrong_evaluator_identity_rejected(self):
        with self.assertRaisesRegex(ValueError, "identity"):
            audit(self.root, self.pins, evaluator_sha256="f" * 64)

    def test_after_snapshot_from_other_case_is_rejected_without_reference(self):
        self.put(
            "delivery-01/delivery.json",
            {"schema": "ndu.real.delivery.v1", "case_id": "other", "text": "wrong"},
        )
        self.put(
            "delivery-01/evaluation.json",
            {
                "schema": "ndu.real.independent-evaluation.v1",
                "case_id": "other",
                "evaluator_source_sha256": self.evaluator,
                "delivery_sha256": self.pins["delivery-01/delivery.json"],
            },
        )
        with self.assertRaisesRegex(ValueError, "identity"):
            self.run_audit(None)

    def test_nonwrite_step_identity_is_also_required(self):
        trajectory = json.loads((self.root / "trajectory.json").read_text())
        trajectory["steps"].append(
            {
                "step": 1,
                "case_id": "other",
                "action": {"action": "STOP", "arguments": {}},
            }
        )
        self.put("trajectory.json", trajectory)
        with self.assertRaisesRegex(ValueError, "identities"):
            self.run_audit(None)

    def test_same_case_reference_differs_from_actual_evaluator_reference(self):
        self.put(
            "reference.json",
            {
                "case_id": "case",
                "field": "company",
                "expected_text": "another-reference",
            },
        )
        with self.assertRaisesRegex(ValueError, "identity"):
            self.run_audit()


if __name__ == "__main__":
    unittest.main()
