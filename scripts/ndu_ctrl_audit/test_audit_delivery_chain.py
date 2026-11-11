"""Adversarial, synthetic checks; not a native WRITE_TEXT reproduction."""
import copy
import hashlib
import json
import unittest

from audit_delivery_chain import audit, audit_observed, STAGES


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



def observed():
    x = valid()
    x["schema"] = "ctrl.delivery-chain.observed.v2"
    x["identity"] = {
        "source_tree_sha256": "d" * 64,
        "evaluator_sha256": "e" * 64,
        "run_id": "run-1",
        "task_id": "task-1",
        "episode_id": "episode-1",
        "evidence_cutoff_ns": 200,
    }
    digest = hashlib.sha256(json.dumps(
        x["identity"], sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    for i, stage in enumerate(STAGES):
        x["stages"][stage]["identity_sha256"] = digest
        x["stages"][stage]["observed_ns"] = 100 + i
    x["candidate_inventory"] = [
        {"candidate_id": "c1", "payload_sha256": "a" * 64},
        {"candidate_id": "c2", "payload_sha256": "c" * 64},
    ]
    x["selected_index"] = 0
    x["launch"] = {
        "exit_code": 0,
        "enforced_before_actor_exec": True,
        "run_id": "run-1",
        "episode_id": "episode-1",
        "wire_sha256": "b" * 64,
    }
    return x


class ObservedAuditTest(unittest.TestCase):
    def test_consistent_observed_claims_not_owner_authentication(self):
        self.assertEqual(audit_observed(observed()), (True, []))

    def test_v1_receipt_cannot_claim_observed(self):
        self.assertIn("BAD_OBSERVED_SCHEMA", audit_observed(valid())[1])

    def test_missing_launch_is_unknown(self):
        x = observed()
        del x["launch"]
        self.assertIn("ISOLATED_ACTOR_NOT_COMPLETED", audit_observed(x)[1])

    def test_nonzero_bool_and_unisolated_launch_fail_closed(self):
        for field, value in (("exit_code", 1), ("exit_code", False),
                             ("enforced_before_actor_exec", False),
                             ("enforced_before_actor_exec", 1)):
            with self.subTest(field=field, value=value):
                x = observed()
                x["launch"][field] = value
                self.assertIn("ISOLATED_ACTOR_NOT_COMPLETED", audit_observed(x)[1])

    def test_wrong_actor_wire(self):
        x = observed()
        x["launch"]["wire_sha256"] = "f" * 64
        self.assertIn("ACTOR_WIRE_DRIFT", audit_observed(x)[1])

    def test_wrong_launch_episode(self):
        x = observed()
        x["launch"]["episode_id"] = "other"
        self.assertIn("LAUNCH_IDENTITY_DRIFT", audit_observed(x)[1])

    def test_selected_index_must_be_recorded_and_correct(self):
        for idx in (None, False, 1, 2, -1):
            with self.subTest(index=idx):
                x = observed()
                x["selected_index"] = idx
                errs = audit_observed(x)[1]
                self.assertTrue(
                    "UNKNOWN_SELECTED_INDEX" in errs
                    or "SELECTED_INDEX_PAYLOAD_DRIFT" in errs
                )

    def test_duplicate_candidate_id(self):
        x = observed()
        x["candidate_inventory"][1]["candidate_id"] = "c1"
        self.assertIn("INVALID_CANDIDATE_INVENTORY", audit_observed(x)[1])

    def test_bad_stage_binding(self):
        x = observed()
        x["stages"]["evaluated"]["identity_sha256"] = "f" * 64
        self.assertIn("evaluated:IDENTITY_BINDING_DRIFT", audit_observed(x)[1])

    def test_bad_cutoff_and_reordered_times(self):
        x = observed()
        x["stages"]["evaluated"]["observed_ns"] = 201
        self.assertIn("evaluated:INVALID_OBSERVATION_TIME", audit_observed(x)[1])
        x = observed()
        x["stages"]["delivered"]["observed_ns"] = 101
        self.assertIn("delivered:INVALID_OBSERVATION_TIME", audit_observed(x)[1])

    def test_negative_observation_time(self):
        x = observed()
        x["stages"]["candidate"]["observed_ns"] = -1
        self.assertIn("candidate:INVALID_OBSERVATION_TIME", audit_observed(x)[1])

    def test_missing_identity(self):
        x = observed()
        del x["identity"]
        self.assertIn("INVALID_OWNER_BOUND_IDENTITY", audit_observed(x)[1])

if __name__ == "__main__":
    unittest.main()
