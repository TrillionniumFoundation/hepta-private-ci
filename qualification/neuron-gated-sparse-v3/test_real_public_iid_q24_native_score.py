"""Pure Python fail-closed acceptance tests for public IID native Q24 scoring.

No native Rust call or actual public pretrained Encoder is mocked as evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from real_public_iid_q24_native_score import (
    Refused, bin_metrics, frozen_single_case_trace, independent_head_margin,
    nearest_rank_us, run, bind_original_public_fit_and_heldout,
    verify_original_physical_public_q24_features,
)


def good():
    truth=[1]*8+[0]*24
    native=[
        {"logit_q24": 1<<24, "status":"ACCEPT_POSITIVE_RESEARCH_ONLY"}
        for _ in range(8)
    ]+[
        {"logit_q24": -(1<<24), "status":"ACCEPT_NEGATIVE_RESEARCH_ONLY"}
        for _ in range(24)
    ]
    return truth,native


def row():
    return {
        "case_id":"held:test-case",
        "source_text_sha256":"7"*64,
        "feature_q24":[i*(1<<20) for i in range(32)],
        "split":"heldout",
    }


class PublicQ24NativeScoreProtocolTests(unittest.TestCase):
    def _public_fit_fixture(self):
        # Shared test fixture only, no independent public Encoder claim.
        from test_real_public_iid_q24_physical_train import stub_inputs
        from real_public_iid_q24_native_score import digest
        fit, plan = stub_inputs()
        original = {
            "input_id": "mock original public source identity",
            "fit": [
                {"id": row["case_id"],
                 "text": "mock text " + str(index),
                 "label": row["train_label"]}
                for index, row in enumerate(fit["rows"])
            ],
            "heldout": [
                {"id": f"held:{i}", "text": f"mock heldout {i}"}
                for i in range(32)
            ],
        }
        fit["source_input_id"] = original["input_id"]
        held = {
            "source_input_id": original["input_id"],
            "input_feature_snapshot_sha256":
                fit["input_feature_snapshot_sha256"],
            "rows": [
                {"case_id": row["id"], "split": "heldout",
                 "source_text_sha256":
                     digest(row["text"].encode("utf-8")),
                 "feature_q24": [0]*32}
                for row in original["heldout"]
            ],
        }
        result = bind_original_public_fit_and_heldout(
            original, fit, held, plan
        )
        self.assertEqual(result["real_public_train_sample_count"],64)
        self.assertEqual(result["real_public_unlabeled_heldout_count"],32)
        self.assertTrue(result["actual_fit_label_identities_bound_to_original_dataset"])
        self.assertFalse(result["signed_independent_source_owner_verified"])
        return original, fit, held, plan

    def test_public_train_bytes_match_original_registered_fit_labels(self):
        original, fit, held, plan = self._public_fit_fixture()
        self.assertEqual(len(original["fit"]),64)
        self.assertEqual(len(held["rows"]),32)

    def test_reject_modified_original_fit_label_after_physical_training(self):
        original, fit, held, plan = (
            self._public_fit_fixture()
        )
        original["fit"][2]["label"] = (original["fit"][2]["label"]+1)%4
        with self.assertRaisesRegex(Refused,"training weights not bound"):
            bind_original_public_fit_and_heldout(original,fit,held,plan)

    def test_reject_swapped_training_source_text_sha_after_training(self):
        original, fit, held, plan = (
            self._public_fit_fixture()
        )
        fit["rows"][0]["source_text_sha256"] = "0"*64
        with self.assertRaisesRegex(Refused,"training weights not bound"):
            bind_original_public_fit_and_heldout(original,fit,held,plan)

    def test_reject_heldout_original_registry_substitution(self):
        original, fit, held, plan = (
            self._public_fit_fixture()
        )
        held["rows"][0]["case_id"] = "foreign-heldout-case"
        with self.assertRaisesRegex(Refused,"heldout source"):
            bind_original_public_fit_and_heldout(original,fit,held,plan)

    def _physical_feature_fixture(self, root: Path):
        original, fit, held, plan = self._public_fit_fixture()
        from real_public_iid_q24_native_score import digest
        rows = [
            {
                "case_id": row["case_id"],
                "split": row["split"],
                "source_text_sha256": row["source_text_sha256"],
                "feature_q24": row["feature_q24"],
            }
            for row in fit["rows"]+held["rows"]
        ]
        encode = lambda obj: (
            json.dumps(obj,sort_keys=True,indent=2,allow_nan=False)+"\n"
        ).encode("utf-8")
        registry = {
            "fit_case_ids": [r["case_id"] for r in fit["rows"]],
            "heldout_case_ids": [r["case_id"] for r in held["rows"]],
        }
        saved_registry = encode(registry)
        projector = b"mock projectors not genuine ModernBERT weights"
        encoder_sha = digest(b"mock pretrained Encoder only")
        snapshot = {
            "schema": "hepta.neuron.public-encoder-q24-feature-snapshot.v1",
            "encoder_sha256": encoder_sha,
            "projection_sha256": digest(projector),
            "registry_sha256": digest(saved_registry),
            "projection_fit_case_ids": registry["fit_case_ids"],
            "feature_rows": rows,
            "claimed_independent_provenance": False,
            "production_qualification": False,
            "ndu_eligible": False,
        }
        snapshot_raw=encode(snapshot)
        frozen_sha=digest(snapshot_raw)
        fit["input_feature_snapshot_sha256"]=frozen_sha
        held["input_feature_snapshot_sha256"]=frozen_sha
        producer={
            "schema": "hepta.neuron.actual-public-encoder-q24-producer.v1",
            "encoder_snapshot_sha256": encoder_sha,
            "projection_safetensors_sha256": digest(projector),
            "registry_sha256": digest(saved_registry),
            "snapshot_sha256": frozen_sha,
            "original_public_input_id": original["input_id"],
            "real_pretrained_encoder_invoked": True,
            "physical_encoder_invocations": 96,
            "train_only_projection_fit_count": 64,
            "heldout_projection_fit_count": 0,
            "projection_owner_signature_verified": False,
            "production_qualification": False,
            "ndu_eligible": False,
        }
        for name, raw in {
            "snapshot.json": snapshot_raw,
            "registry.json": saved_registry,
            "projection.safetensors": projector,
            "producer-receipt.json": encode(producer),
        }.items():
            (root/name).write_bytes(raw)
        return original,fit,held

    def test_physical_q24_feature_receipt_requires_exact_96_vectors(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            original,fit,held=self._physical_feature_fixture(root)
            report=verify_original_physical_public_q24_features(root,fit,held,original)
            self.assertTrue(report["all_96_fit_and_heldout_vectors_reopened_and_equal"])
            self.assertFalse(report["independently_signed_encoder_or_projection_verified"])
            self.assertEqual(report["authority"],"DENY_ALL")

    def test_swapped_heldout_q24_feature_cannot_retain_original_sha(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            original,fit,held=self._physical_feature_fixture(root)
            held["rows"][0]["feature_q24"][0]+=1
            with self.assertRaisesRegex(Refused,"differs from physical Encoder"):
                verify_original_physical_public_q24_features(root,fit,held,original)

    def test_swapped_physical_projector_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            original,fit,held=self._physical_feature_fixture(root)
            (root/"projection.safetensors").write_bytes(b"forged other projector")
            with self.assertRaisesRegex(Refused,"substituted"):
                verify_original_physical_public_q24_features(root,fit,held,original)

    def test_expensive_scorer_cannot_shadow_module_path_constructor(self):
        # This catches the actual source bug where run() referenced Path
        # before a function-local "from pathlib import Path" statement.
        # Source-only gate runs without Rust, pretrained weights, or labels.
        self.assertNotIn("Path", run.__code__.co_varnames)
        self.assertIn("models_root", run.__code__.co_names)

    def test_full_heldout_census_exact_delivery(self):
        labels,outputs=good()
        result=bin_metrics(labels,outputs)
        self.assertEqual(result["original_heldout_opportunities"],32)
        self.assertEqual(result["actual_accepted_decisions"],32)
        self.assertEqual(result["abstentions"],0)
        self.assertEqual(result["delivered_accuracy_with_abstain_counted_wrong"],1)
        self.assertEqual(result["positive_recall_8"],1)
        self.assertEqual(result["negative_specificity_24"],1)
        self.assertEqual(result["balanced_accuracy_with_abstain_counted_wrong"],1.0)
        self.assertEqual(result["true_positives"],8)
        self.assertEqual(result["true_negatives"],24)
        self.assertEqual(result["false_positives"],0)
        self.assertEqual(result["false_negatives"],0)

    def test_abstain_is_never_counted_as_correct(self):
        labels,outputs=good()
        for j in [0,1,8,9]:
            outputs[j]={"logit_q24":0,"status":"QUANTIZATION_AMBIGUOUS_ABSTAIN"}
        result=bin_metrics(labels,outputs)
        self.assertEqual(result["abstentions"],4)
        self.assertEqual(result["correct_nonabstained"],28)
        self.assertEqual(result["delivered_accuracy_with_abstain_counted_wrong"],28/32)
        self.assertEqual(result["coverage"],28/32)

    def test_positive_status_cannot_hide_negative_logit(self):
        truth,rows=good()
        rows[0]["logit_q24"]=-(1<<24)
        with self.assertRaisesRegex(Refused,"sign margin"):
            bin_metrics(truth,rows)

    def test_zero_logit_cannot_be_accepted_as_negative(self):
        truth,rows=good()
        rows[-1]={"logit_q24":0,"status":"ACCEPT_NEGATIVE_RESEARCH_ONLY"}
        with self.assertRaisesRegex(Refused,"sign margin"):
            bin_metrics(truth,rows)

    def test_no_missing_positive_labels_or_rows(self):
        truth,rows=good()
        with self.assertRaises(Refused):
            bin_metrics(truth[:31],rows)
        truth[0]=0
        with self.assertRaisesRegex(Refused,"positive denominator"):
            bin_metrics(truth,rows)

    def test_noninteger_native_logit_rejected(self):
        for value in (True,0.0,"16777216",None):
            truth,rows=good()
            rows[0]["logit_q24"]=value
            with self.assertRaises(Refused):
                bin_metrics(truth,rows)

    def test_unknown_head_status_not_a_prediction(self):
        truth,rows=good()
        rows[0]["status"]="ACCEPT_AUTHORIZED_FINAL_USE"
        with self.assertRaises(Refused):
            bin_metrics(truth,rows)

    def test_single_case_native_trace_keeps_independent_reset(self):
        original=row()
        trace=frozen_single_case_trace(original, task_id=0)
        self.assertEqual(trace["schema"],"hepta.neuron.physical-q24-shadow-trace.v1")
        self.assertEqual(len(trace["events"]),1)
        self.assertEqual(trace["events"][0]["temporal_drive_q24"],original["feature_q24"])
        self.assertEqual(trace["events"][0]["prediction_q24"],[0]*32)
        self.assertNotIn("label",trace)
        self.assertNotIn("event_time_utc",trace)
        self.assertNotIn("future",trace)
        self.assertTrue(all(len(trace[key])==64 for key in
                            ("scope_digest","objective_digest","ndu_digest","body_digest")))

    def test_independent_head_sign_boundary_and_abstention(self):
        width=16
        boundary=width*9+1
        for logit,status in (
            (0,"QUANTIZATION_AMBIGUOUS_ABSTAIN"),
            (boundary//2,"QUANTIZATION_AMBIGUOUS_ABSTAIN"),
            (boundary//2+1,"ACCEPT_POSITIVE_RESEARCH_ONLY"),
            (-(boundary//2+1),"ACCEPT_NEGATIVE_RESEARCH_ONLY"),
        ):
            result=independent_head_margin({
                "activation_q24":[0]*width,
                "quantized_head_logit_q24":logit,
                "head_sign_margin_twice_q24_lsb":boundary,
                "head_sign_margin_status":status,
            },width)
            self.assertEqual(result["logit_q24"],logit)
            self.assertEqual(result["status"],status)

    def test_forged_native_head_margin_and_boolean_types_fail(self):
        row={
            "activation_q24":[0]*16,
            "quantized_head_logit_q24":1000000,
            "head_sign_margin_twice_q24_lsb":145,
            "head_sign_margin_status":"ACCEPT_POSITIVE_RESEARCH_ONLY",
        }
        self.assertEqual(independent_head_margin(row,16)["status"],
                         "ACCEPT_POSITIVE_RESEARCH_ONLY")
        for change in (
            {"head_sign_margin_twice_q24_lsb":144},
            {"head_sign_margin_twice_q24_lsb":True},
            {"head_sign_margin_status":"QUANTIZATION_AMBIGUOUS_ABSTAIN"},
            {"quantized_head_logit_q24":True},
            {"activation_q24":[0]*15},
            {"activation_q24":[0]*15+[True]},
        ):
            corrupted=dict(row,**change)
            with self.assertRaises(Refused):
                independent_head_margin(corrupted,16)

    def test_task_binding_changes_native_q24_objective(self):
        original=row()
        a=frozen_single_case_trace(original,task_id=0)
        b=frozen_single_case_trace(original,task_id=1)
        self.assertNotEqual(a["objective_digest"], b["objective_digest"])
        self.assertEqual(a["events"], b["events"])
        for forged in (True,-1,4,0.0,"0"):
            with self.assertRaises(Refused):
                frozen_single_case_trace(original,task_id=forged)

    def test_true_public_heldout_label_field_is_forbidden(self):
        original=row()
        original["label"]=0
        with self.assertRaises(Refused):
            frozen_single_case_trace(original, task_id=0)

    def test_wrong_q24_shape_or_type_refused(self):
        for variant in (True,1.0,"1",8*(1<<24)+1):
            record=row()
            record["feature_q24"][0]=variant
            with self.assertRaises(Refused):
                frozen_single_case_trace(record, task_id=0)
        record=row()
        record["feature_q24"].pop()
        with self.assertRaises(Refused):
            frozen_single_case_trace(record, task_id=0)

    def test_real_cold_process_wall_percentiles_use_nearest_rank(self):
        values=[i*1000 for i in range(1,65)]
        self.assertEqual(nearest_rank_us(values,50),32)
        self.assertEqual(nearest_rank_us(values,95),61)
        self.assertEqual(nearest_rank_us(values,99),64)

    def test_cannot_claim_missing_or_forged_wall_census(self):
        original=[i*1000 for i in range(1,65)]
        for broken in (original[:63], original+[65000],
                       [True]+original[1:], [0]+original[1:],
                       [1.0]+original[1:]):
            with self.assertRaises(Refused):
                nearest_rank_us(broken,99)
        with self.assertRaises(Refused):
            nearest_rank_us(original,100)

    def test_not_a_fake_temporal_sequence(self):
        original=row()
        original["sequence"]=2
        with self.assertRaises(Refused):
            frozen_single_case_trace(original, task_id=0)


if __name__=="__main__":
    unittest.main()
