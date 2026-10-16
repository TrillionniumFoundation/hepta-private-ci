"""Pure Python fail-closed acceptance tests for public IID native Q24 scoring.

No native Rust call or actual public pretrained Encoder is mocked as evidence.
"""
from __future__ import annotations

import copy
import unittest

from real_public_iid_q24_native_score import (
    Refused, bin_metrics, frozen_single_case_trace, independent_head_margin,
    nearest_rank_us,
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
    def test_full_heldout_census_exact_delivery(self):
        labels,outputs=good()
        result=bin_metrics(labels,outputs)
        self.assertEqual(result["original_heldout_opportunities"],32)
        self.assertEqual(result["actual_accepted_decisions"],32)
        self.assertEqual(result["abstentions"],0)
        self.assertEqual(result["delivered_accuracy_with_abstain_counted_wrong"],1)
        self.assertEqual(result["positive_recall_8"],1)
        self.assertEqual(result["negative_specificity_24"],1)

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
                frozen_single_case_trace(record)
        record=row()
        record["feature_q24"].pop()
        with self.assertRaises(Refused):
            frozen_single_case_trace(record)

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
