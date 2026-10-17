"""Fail-closed source-only tests for V2 artifact custody (no actual model claims)."""
import copy
import tempfile
import unittest
from pathlib import Path

from original_receipt_audit_v2 import ARMS, CANDIDATES, COHORT_SHA, MATERIAL_SHA, audit, original_zip


class NegativeTests(unittest.TestCase):
    def setUp(self):
        self.runs = {}
        self.review = {
            "schema":"hepta.stem.optimal.independent-review.v1", "case_count":32,
            "publisher_original_sha_verified":True, "independent_publisher_label_recount":True,
            "source_independent_families":1, "training_continuation_future_windows":0,
            "production_authorized":False, "stem_winner_verified":False,
            "ndu_benefit_verified":False, "trained_4096_cells":False,
            "host_cost_attestation":False, "human_semantic_evaluation":False,
            "matched_421m_total_lifecycle":False, "disposition":"HOLD_NO_GO", "models":{}
        }
        for name in CANDIDATES:
            cost = {
                "encoder_forward_batches":6, "physical_encoder_sequences":96,
                "energy_joules":None,"p99_latency_ms":None,
                "elapsed_cpu_seconds":1., "elapsed_wall_seconds":1.,
                "head_train_wall_seconds":.05, "model_download_load_wall_seconds":.5,
                "feature_encode_wall_seconds":.1, "maxrss_bytes":500000000
            }
            self.runs[name] = {
                "schema":"hepta.stem.optimal.physical-unattested.v1","candidate":name,
                "source_plan_sha256":COHORT_SHA,"material_manifest_sha256":MATERIAL_SHA,
                "optimizer_steps":100,"head_parameters":27656, "initial_head_sha256":"a"*64,
                "production_authorized":False,"physical_claim_unattested":True,
                "disposition":"HOLD_NO_GO","future_windows_verified":0,
                "real_4096_cell_training_verified":False,"cost":cost,
                "rows":[{"case_id":"heldout:"+format(i,"064x"),"source_sha256":format(i,"064x"),
                         "scores":{arm:[.25,.25,.25,.25] for arm in ARMS}} for i in range(32)]
            }
            self.review["models"][name] = {
                "cost_observed_unattested":cost,
                "arms":{arm:{"n":32,"correct":8,"mean_multiclass_brier":.75} for arm in ARMS}
            }

    def expect_denied(self):
        with self.assertRaises(ValueError):
            audit(self.runs, self.review)

    def test_positive_synthetic_still_no_go(self):
        result = audit(self.runs, self.review)
        self.assertEqual(result["authority"],"DENY_ALL")
        self.assertFalse(result["stem_winner_verified"])
        self.assertFalse(result["this_v2_recomputed_publisher_labels"])

    def test_fake_model_winner(self):
        self.review["stem_winner_verified"] = True
        self.expect_denied()

    def test_fake_future(self):
        self.review["training_continuation_future_windows"] = 2
        self.expect_denied()

    def test_fake_host_attestation(self):
        self.review["host_cost_attestation"] = True
        self.expect_denied()

    def test_wrong_train_budget(self):
        self.runs["granite47"]["optimizer_steps"] = 101
        self.expect_denied()

    def test_wrong_encoder_count(self):
        self.runs["granite97"]["cost"]["encoder_forward_batches"] = 1
        self.expect_denied()

    def test_changed_initialization(self):
        self.runs["mmbert140"]["initial_head_sha256"] = "b"*64
        self.expect_denied()

    def test_held_label_leak(self):
        self.runs["granite47"]["rows"][0]["gold"] = 0
        self.expect_denied()

    def test_wrong_model_case(self):
        self.runs["granite47"]["rows"][0]["source_sha256"] = "f"*64
        self.expect_denied()

    def test_nonfinite_probability(self):
        self.runs["granite47"]["rows"][0]["scores"]["learned"][0] = float("nan")
        self.expect_denied()

    def test_duplicate_model_case(self):
        self.runs["granite47"]["rows"][0] = copy.deepcopy(self.runs["granite47"]["rows"][1])
        self.expect_denied()

    def test_modified_original_zip(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d)/"original.zip"
            fake.write_bytes(b"not signed original bytes")
            with self.assertRaises(ValueError):
                original_zip(fake, "granite47")


if __name__ == "__main__":
    unittest.main()
