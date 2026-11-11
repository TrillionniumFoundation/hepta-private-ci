"""Adversarial, synthetic checks; not a native WRITE_TEXT reproduction."""
import copy
import unittest

from audit_delivery_chain import audit


def valid():
    h, w = "a" * 64, "b" * 64
    return {"schema": "ctrl.delivery-chain.v1", "stages": {
        "candidate": {"candidate_id": "c1", "payload_sha256": h},
        "selected": {"candidate_id": "c1", "payload_sha256": h},
        "serialized": {"candidate_id": "c1", "payload_sha256": h, "wire_sha256": w},
        "delivered": {"candidate_id": "c1", "wire_sha256": w, "delivery_receipt_id": "r1"},
        "evaluated": {"candidate_id": "c1", "wire_sha256": w, "delivery_receipt_id": "r1", "score": 0},
    }}


class DeliveryAuditTest(unittest.TestCase):
    def test_valid_zero_score_is_not_rewritten(self):
        self.assertEqual(audit(valid()), (True, []))

    def test_each_stage_required(self):
        for stage in list(valid()["stages"]):
            with self.subTest(stage=stage):
                x = valid()
                del x["stages"][stage]
                self.assertFalse(audit(x)[0])

    def test_candidate_switch(self):
        x = valid()
        x["stages"]["selected"]["candidate_id"] = "other"
        self.assertIn("CANDIDATE_ID_DRIFT", audit(x)[1])

    def test_payload_switch(self):
        x = valid()
        x["stages"]["serialized"]["payload_sha256"] = "c" * 64
        self.assertIn("SELECTED_PAYLOAD_DRIFT", audit(x)[1])

    def test_wire_switch(self):
        x = valid()
        x["stages"]["delivered"]["wire_sha256"] = "c" * 64
        self.assertIn("WIRE_PAYLOAD_DRIFT", audit(x)[1])

    def test_evaluator_receipt_switch(self):
        x = valid()
        x["stages"]["evaluated"]["delivery_receipt_id"] = "another"
        self.assertIn("EVALUATOR_DELIVERY_RECEIPT_DRIFT", audit(x)[1])

    def test_missing_and_bad_digest(self):
        for change in ("missing", "bad"):
            x = valid()
            if change == "missing":
                del x["stages"]["delivered"]["wire_sha256"]
            else:
                x["stages"]["delivered"]["wire_sha256"] = "bad"
            self.assertFalse(audit(x)[0])

    def test_invalid_score(self):
        for score in (None, True, -0.1, 1.1, "0"):
            x = valid()
            x["stages"]["evaluated"]["score"] = score
            self.assertFalse(audit(x)[0])


if __name__ == "__main__":
    unittest.main()
