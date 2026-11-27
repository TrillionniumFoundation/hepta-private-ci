"""Negative tests: real public IID Q24 model inputs are NOT future windows."""
from __future__ import annotations

import copy
import hashlib
import unittest

from real_public_iid_q24_inputs import Refused, bind_public_iid, canonical, digest
from real_encoder_q24_snapshot_gate import Refused as GateRefused


def h(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def example():
    intents = [
        "card_arrival", "cash_withdrawal_not_recognised",
        "exchange_rate", "lost_or_stolen_phone",
    ]
    fit = [
        {"id": f"fit:{i}", "text": f"public fit utterance {i}", "label": i % 4}
        for i in range(64)
    ]
    held = [
        {"id": f"held:{i}", "text": f"public heldout utterance {i}"}
        for i in range(32)
    ]
    original = {
        "intents": intents, "fit": fit, "heldout": held,
        "input_id": h("public source preregistered fixture only"),
    }
    registry = {
        "fit_case_ids": [r["id"] for r in fit],
        "heldout_case_ids": [r["id"] for r in held],
    }
    encoder, projection = h("synthetic fake model"), h("fake fitted projector")
    registry_sha = digest(canonical(registry))
    rows = [
        {"case_id": r["id"], "split": split,
         "source_text_sha256": digest(r["text"].encode()),
         "feature_q24": [int((i + j) % 32) for j in range(32)]}
        for split, group in (("fit", fit), ("heldout", held))
        for i, r in enumerate(group)
    ]
    snapshot = {
        "schema": "hepta.neuron.public-encoder-q24-feature-snapshot.v1",
        "encoder_sha256": encoder, "projection_sha256": projection,
        "registry_sha256": registry_sha,
        "projection_fit_case_ids": registry["fit_case_ids"],
        "feature_rows": rows,
        "claimed_independent_provenance": False,
        "production_qualification": False, "ndu_eligible": False,
    }
    snapshot_sha = digest(canonical(snapshot))
    receipt = {
        "schema": "hepta.neuron.actual-public-encoder-q24-producer.v1",
        "original_public_input_id": original["input_id"],
        "real_pretrained_encoder_invoked": True,
        "physical_encoder_invocations": 96,
        "train_only_projection_fit_count": 64,
        "heldout_projection_fit_count": 0,
        "projection_safetensors_sha256": projection,
        "registry_sha256": registry_sha,
        "snapshot_sha256": snapshot_sha,
        "encoder_snapshot_sha256": encoder,
        "production_qualification": False, "ndu_eligible": False,
        "original_selected_v1_no_change_verified": False,
        "projection_owner_signature_verified": False,
    }
    return snapshot, registry, receipt, original, projection, registry_sha, snapshot_sha


def bind(data):
    s, r, receipt, original, projection, registry_sha, snapshot_sha = data
    return bind_public_iid(
        s, r, receipt, original,
        projection_sha256=projection, registry_sha256=registry_sha,
        snapshot_sha256=snapshot_sha,
    )


class PublicIIDFeatureBindingTests(unittest.TestCase):
    def test_exact_registered_public_features_and_train_labels(self):
        fit, held, plan = bind(example())
        self.assertEqual(len(fit["rows"]), 64)
        self.assertEqual(len(held["rows"]), 32)
        self.assertEqual(len(plan["binary_tasks"]), 4)
        self.assertEqual(plan["candidate_private_serialized_byte_budgets"], [8192, 32768])
        self.assertEqual(fit["rows"][0]["train_label"], 0)
        self.assertEqual(fit["rows"][63]["train_label"], 3)
        self.assertTrue(all("train_label" not in row and "label" not in row
                            for row in held["rows"]))
        self.assertTrue(all("event_time_utc" not in row and "sequence" not in row
                            for row in fit["rows"] + held["rows"]))
        self.assertIn("NOT_FUTURE", fit["temporal_observation_kind"])
        self.assertFalse(plan["training_execution_performed"])
        self.assertFalse(plan["independent_heldout_labels_joined"])
        self.assertFalse(plan["selected_original_v1_no_change_a0_verified"])
        self.assertEqual(plan["decision"], "NO_MODEL_PROMOTION")

    def test_changed_encoder_digest_denied(self):
        data = list(copy.deepcopy(example()))
        data[2]["encoder_snapshot_sha256"] = h("injected model")
        with self.assertRaises(GateRefused):
            bind(data)

    def test_changed_original_public_case_identity_denied(self):
        data = list(copy.deepcopy(example()))
        data[2]["original_public_input_id"] = h("other source")
        with self.assertRaisesRegex(Refused, "source"):
            bind(data)

    def test_wrong_feature_text_digest_denied(self):
        data = list(copy.deepcopy(example()))
        data[0]["feature_rows"][1]["source_text_sha256"] = h("different text")
        with self.assertRaisesRegex(Refused, "original public text"):
            bind(data)

    def test_missing_heldout_q24_row_denied(self):
        data = list(copy.deepcopy(example()))
        data[0]["feature_rows"].pop()
        with self.assertRaises(GateRefused):
            bind(data)

    def test_duplicate_q24_feature_row_denied(self):
        data = list(copy.deepcopy(example()))
        data[0]["feature_rows"][7]["case_id"] = data[0]["feature_rows"][0]["case_id"]
        with self.assertRaises(GateRefused):
            bind(data)

    def test_heldout_label_injected_into_original_inputs_denied(self):
        data = list(copy.deepcopy(example()))
        data[3]["heldout"][0]["label"] = 1
        with self.assertRaisesRegex(Refused, "heldout label"):
            bind(data)

    def test_projection_declares_heldout_fit_denied(self):
        data = list(copy.deepcopy(example()))
        data[0]["projection_fit_case_ids"].append("held:0")
        with self.assertRaises(GateRefused):
            bind(data)

    def test_forged_no_change_authority_denied(self):
        data = list(copy.deepcopy(example()))
        data[2]["original_selected_v1_no_change_verified"] = True
        with self.assertRaisesRegex(Refused, "non-authorizing"):
            bind(data)

    def test_forged_signed_projector_denied(self):
        data = list(copy.deepcopy(example()))
        data[2]["projection_owner_signature_verified"] = True
        with self.assertRaisesRegex(Refused, "non-authorizing"):
            bind(data)

    def test_mismatched_physical_snapshot_digest_denied(self):
        data = list(copy.deepcopy(example()))
        data[6] = h("mutated physical feature bytes")
        with self.assertRaisesRegex(Refused, "SHA drift"):
            bind(data)

    def test_no_fake_future_timestamps_or_quality_claim(self):
        fit, held, plan = bind(example())
        self.assertTrue(fit["fit_labels_only"])
        self.assertFalse(held["holdout_labels_exposed"])
        self.assertEqual(plan["fit_case_count"], 64)
        self.assertEqual(plan["heldout_case_count"], 32)
        self.assertFalse(plan["longitudinal_or_future_task_efficacy_claim_permitted"])
        self.assertFalse(fit["production_qualification"])
        self.assertFalse(held["ndu_eligible"])


if __name__ == "__main__":
    unittest.main()
