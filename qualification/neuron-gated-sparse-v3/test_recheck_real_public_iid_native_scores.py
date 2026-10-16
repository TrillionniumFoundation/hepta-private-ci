"""Pure-Python independent original-label replay of sealed Q24 IID outcomes.

All synthetic fixtures here are contract tests, not actual BANKING77/ModernBERT
results. No torch/rust/native execution dependency or model selection.
"""
from __future__ import annotations

import copy
import hashlib
import unittest

from recheck_real_public_iid_native_scores import (
    Rejected, recheck_report, sha
)
from real_public_iid_q24_native_score import bin_metrics, canonical

ARMS=("v2","v3","ssm","min_gru")
BUDGETS=(8192,32768)
Q=1<<24


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def fixture():
    public={
        "input_id":"pure-synthetic-stub-not-signed",
        "fit":[{"id":f"fit:{i}","text":f"mock fit {i}","label":i//16}
               for i in range(64)],
        "heldout":[{"id":f"held:{i}","text":f"mock heldout {i}"}
                   for i in range(32)],
    }
    truth=[i//8 for i in range(32)]
    observer={"rows":[{"id":v["id"],"label":truth[i]}
                      for i,v in enumerate(public["heldout"])]}
    models, observations=[],[]
    for task in range(4):
        for cap in BUDGETS:
            for arm in ARMS:
                model_sha=digest(f"mock never-trained {task}/{cap}/{arm}")
                width=54
                bound=9*width+1
                cases=[{
                    "case_id":case["id"],
                    "source_text_sha256":digest(case["text"]),
                    "logit_q24":-Q,
                    "head_sign_margin_status":"ACCEPT_NEGATIVE_RESEARCH_ONLY",
                    "head_sign_margin_twice_q24_lsb":bound,
                    "native_cold_checkpoint_sha256":digest(f"{task}/{cap}/{arm}/{i}"),
                } for i,case in enumerate(public["heldout"])]
                rec={"task_id":task,"arm":arm,"serialized_byte_budget":cap,
                     "hidden_width":width,"physical_model_sha256":model_sha,
                     "cases":cases}
                metrics=bin_metrics([int(v==task) for v in truth],
                                    [{"logit_q24":-Q,
                                      "status":"ACCEPT_NEGATIVE_RESEARCH_ONLY"}]*32)
                metrics.update({
                    "task_id":task,"arm":arm,"serialized_byte_budget":cap,
                    "physical_model_sha256":model_sha,
                    "heldout_unlabeled_prediction_sha256":sha(canonical(rec)),
                    "independent_native_os_processes":64,
                    "independently_checked_original_q24_input_events":32,
                    "isolated_cold_process_wall_p50_micros":5,
                    "isolated_cold_process_wall_p95_micros":11,
                    "isolated_cold_process_wall_p99_micros":21,
                    "full_encoder_worker_runtime_or_target_host_slo_verified":False,
                    "process_wall_includes_binary_startup_model_load_and_json":True,
                })
                models.append(rec);observations.append(metrics)
    report={
        "schema":"hepta.neuron.real-public-iid-native-q24-heldout.v1",
        "decision":"NO_MODEL_SELECTION", "authority":"DENY_ALL",
        "original_heldout_cases":32, "four_binary_tasks":4,
        "trained_private_models":32,
        "fresh_rust_os_process_invocations":2048,
        "unlabeled_prediction_census":1024,
        "all_independent_q24_adapter_head_integer_checks":True,
        "independent_signed_evaluator_custody":False,
        "original_selected_deployed_v1_no_change_a0_verified":False,
        "real_future_window_and_negative_transfer_verified":False,
        "ndu_eligible":False, "production_qualification":False,
        "native_rust_binary_sha256":digest("mock-rust-source-binary"),
        "training_receipt_sha256":digest("mock-training-receipt"),
        "heldout_source_sha256":digest("mock-unlabeled-heldout-file"),
        "original_public_source_input_id":public["input_id"],
        "static_label_prior_control":{
            "correct_cases":24,"true_positive_cases":8,
            "true_negative_cases":24,"delivered_accuracy":.75,
            "balanced_accuracy":.5,
            "positive_recall":0.0,
            "not_original_deployed_v1_no_change":True,
            "not_a_temporal_learning_or_ndu_baseline":True,
        },
        "unlabeled_prediction_records":models,
        "observations":observations,
    }
    return report,public,observer


class IndependentPublicNativeAuditProtocol(unittest.TestCase):
    def check(self, values):
        report,original,labels=values
        return recheck_report(
            report,original,labels,digest("mock-unlabeled-heldout-file"))

    def test_original_1024_records_recomputed_with_no_selection(self):
        result=self.check(fixture())
        self.assertEqual(result["distinct_physical_model_count"],32)
        self.assertEqual(result["independently_recomputed_label_free_native_records"],1024)
        self.assertEqual(result["reported_native_processes"],2048)
        self.assertEqual(len(result["descriptive_recomputed_scores"]),32)
        self.assertTrue(all(x["delivered_accuracy"]==.75
                            for x in result["descriptive_recomputed_scores"]))
        self.assertFalse(result["baseline_original_v1_verified"])
        self.assertFalse(result["ndu_eligible"])
        self.assertFalse(result["production_qualification"])

    def test_changed_unlabeled_output_without_new_sha_rejected(self):
        r,p,o=fixture()
        r["unlabeled_prediction_records"][0]["cases"][0]["logit_q24"]=Q
        with self.assertRaisesRegex(Rejected,"not bound"):
            self.check((r,p,o))

    def test_changed_native_output_even_when_hash_recomputed_rejected(self):
        r,p,o=fixture()
        model=r["unlabeled_prediction_records"][0]
        model["cases"][0]["logit_q24"]=Q
        model["cases"][0]["head_sign_margin_status"]="ACCEPT_POSITIVE_RESEARCH_ONLY"
        r["observations"][0]["heldout_unlabeled_prediction_sha256"]=sha(canonical(model))
        with self.assertRaisesRegex(Rejected,"score changed"):
            self.check((r,p,o))

    def test_wrong_original_heldout_observer_label_rejected(self):
        r,p,o=fixture()
        o["rows"][0]["label"]=3
        with self.assertRaises(Rejected):
            self.check((r,p,o))

    def test_forged_native_head_margin_rejected(self):
        r,p,o=fixture()
        model=r["unlabeled_prediction_records"][0]
        model["cases"][0]["head_sign_margin_twice_q24_lsb"]=1
        r["observations"][0]["heldout_unlabeled_prediction_sha256"]=sha(canonical(model))
        with self.assertRaisesRegex(Rejected,"confidence"):
            self.check((r,p,o))

    def test_foreign_or_duplicate_architecture_or_budget_rejected(self):
        for patch in [
            {"arm":"future_fictional"},
            {"serialized_byte_budget":65536},
            {"task_id":True},
        ]:
            r,p,o=fixture()
            r["unlabeled_prediction_records"][0].update(patch)
            with self.assertRaises(Rejected):
                self.check((r,p,o))

    def test_missing_process_or_wrong_binary_sha_rejected(self):
        for patch in [
            {"fresh_rust_os_process_invocations":2047},
            {"native_rust_binary_sha256":"0"*63},
            {"independent_signed_evaluator_custody":True},
            {"original_selected_deployed_v1_no_change_a0_verified":True},
        ]:
            r,p,o=fixture()
            r.update(patch)
            with self.assertRaises(Rejected):
                self.check((r,p,o))

    def test_fake_v1_zero_parameter_prior_denied(self):
        r,p,o=fixture()
        r["static_label_prior_control"]["not_original_deployed_v1_no_change"]=False
        with self.assertRaisesRegex(Rejected,"fake class-prior"):
            self.check((r,p,o))

    def test_bogus_full_worker_latency_slo_rejected(self):
        r,p,o=fixture()
        r["observations"][0]["full_encoder_worker_runtime_or_target_host_slo_verified"]=True
        with self.assertRaisesRegex(Rejected,"production host"):
            self.check((r,p,o))

    def test_corrupted_checkpoint_identity_rejected(self):
        r,p,o=fixture()
        model=r["unlabeled_prediction_records"][0]
        model["cases"][0]["native_cold_checkpoint_sha256"]="0"*63
        r["observations"][0]["heldout_unlabeled_prediction_sha256"]=sha(canonical(model))
        with self.assertRaisesRegex(Rejected,"checkpoint SHA"):
            self.check((r,p,o))


if __name__=="__main__":
    unittest.main()
