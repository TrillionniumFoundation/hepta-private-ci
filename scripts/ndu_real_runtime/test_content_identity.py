import hashlib
import json
import unittest

from .content_identity import observe_delivery, selection_receipt, validate_selection


class ContentIdentityTests(unittest.TestCase):
    def case(self, selected=0, delivered=None):
        candidates = [{"text": "wrong"}, {"text": "reference"}]
        action = {
            "schema": "ndu.real.actor-action.v1",
            "action": "WRITE_TEXT",
            "arguments": {"text": candidates[selected]["text"]},
        }
        step = {
            "case_id": "private-case",
            "step": 0,
            "action": action,
            "candidate_metadata": candidates,
            "content_selection": selection_receipt(candidates, selected, action),
        }
        raw = json.dumps(
            {
                "case_id": step["case_id"],
                "text": action["arguments"]["text"] if delivered is None else delivered,
            }
        ).encode()
        evaluation = {
            "case_id": step["case_id"],
            "quality": 0,
            "delivery_sha256": hashlib.sha256(raw).hexdigest(),
        }
        return step, raw, evaluation

    def test_wrong_selection_can_be_fully_delivered_with_zero_quality(self):
        step, raw, evaluation = self.case()
        observation = observe_delivery(step, raw, evaluation)
        self.assertTrue(observation["selected_to_evaluator"])
        self.assertEqual(observation["semantic_quality"], 0)
        self.assertNotIn("reference", json.dumps(observation))
        self.assertNotIn("wrong", json.dumps(observation))

    def test_correct_selection_lost_in_delivery_is_detected(self):
        step, raw, evaluation = self.case(selected=1, delivered="wrong")
        observed = observe_delivery(step, raw, evaluation)
        self.assertFalse(observed["serialized_to_delivered"])
        self.assertFalse(observed["selected_to_evaluator"])

    def test_scorer_on_other_bytes_is_detected(self):
        step, raw, evaluation = self.case()
        evaluation["delivery_sha256"] = "0" * 64
        self.assertFalse(
            observe_delivery(step, raw, evaluation)["delivered_to_evaluator"]
        )

    def test_changed_serialization_or_candidate_is_rejected(self):
        step, _, _ = self.case(selected=1)
        step["action"]["arguments"]["text"] = "changed"
        with self.assertRaises(ValueError):
            validate_selection(step)
        step, _, _ = self.case(selected=1)
        step["candidate_metadata"][1]["text"] = "changed"
        with self.assertRaises(ValueError):
            validate_selection(step)

    def test_old_record_does_not_impute_selection(self):
        step, raw, evaluation = self.case()
        del step["content_selection"]
        result = observe_delivery(step, raw, evaluation)
        self.assertIsNone(result["selected_to_evaluator"])
        self.assertTrue(result["serialized_to_delivered"])

    def test_case_mismatch_is_rejected(self):
        step, raw, evaluation = self.case()
        evaluation["case_id"] = "other"
        with self.assertRaises(ValueError):
            observe_delivery(step, raw, evaluation)


if __name__ == "__main__":
    unittest.main()
