"""Pure Python fail-closed acceptance tests for public IID native Q24 scoring.

No native Rust call or actual public pretrained Encoder is mocked as evidence.
"""
from __future__ import annotations

import copy
import unittest

from real_public_iid_q24_native_score import (
    Refused, bin_metrics, frozen_single_case_trace,
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
        trace=frozen_single_case_trace(original)
        self.assertEqual(trace["schema"],"hepta.neuron.physical-q24-shadow-trace.v1")
        self.assertEqual(len(trace["events"]),1)
        self.assertEqual(trace["events"][0]["temporal_drive_q24"],original["feature_q24"])
        self.assertEqual(trace["events"][0]["prediction_q24"],[0]*32)
        self.assertNotIn("label",trace)
        self.assertNotIn("event_time_utc",trace)
        self.assertNotIn("future",trace)
        self.assertTrue(all(len(trace[key])==64 for key in
                            ("scope_digest","objective_digest","ndu_digest","body_digest")))

    def test_true_public_heldout_label_field_is_forbidden(self):
        original=row()
        original["label"]=0
        with self.assertRaises(Refused):
            frozen_single_case_trace(original)

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

    def test_not_a_fake_temporal_sequence(self):
        original=row()
        original["sequence"]=2
        with self.assertRaises(Refused):
            frozen_single_case_trace(original)


if __name__=="__main__":
    unittest.main()
