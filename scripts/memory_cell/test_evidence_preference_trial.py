"""Matching and answerability tests; fixture scores are not model results."""

import copy
import unittest

from balanced_reader_trial import EVIDENCE, report
from selector_answering import ABSTAIN


def rows():
    result = []
    for evidence in EVIDENCE:
        for reader in ("base", "legacy", "preference"):
            empty = evidence == "empty"
            result.append(dict(
                question_id="q", phase="test", family="family", pool_digest="pool",
                arm=f"{evidence}_{reader}", status="succeeded", selected=None if empty else 0,
                answer="Kyoto [E1]" if not empty else ABSTAIN,
                f1=0.0 if empty else 0.5, target_unanswerable=False,
                receipt=dict(base_identity="base", prompt_profile="prompt",
                    input_ids_digest="empty" if empty else "source",
                    delivered_evidence=[] if empty else [{"label": "E1"}]),
            ))
    return result


class PreferenceTrialTests(unittest.TestCase):
    def test_evidence_gain_is_separate_from_candidate_gain(self):
        value = report(rows(), ["q"], candidate="preference")
        self.assertEqual(value["candidate_objective"], "preference")
        self.assertEqual(value["answerable_contrasts"]["test/native/preference"]["family_delta_bounds"], [0.0, 0.0])
        reliance = value["evidence_vs_empty"]["test/native/preference"]
        self.assertEqual(reliance["conditional_f1_delta"], 0.5)
        self.assertFalse(value["production_accepted"])
        self.assertFalse(value["answerable_contrasts"]["test/native/preference"]["significance_established"])

    def test_zero_answerable_gain_cannot_be_hidden_by_protocol_refusal(self):
        records = rows()
        for row in records:
            if row["arm"].endswith("preference"):
                row.update(f1=0.0, answer=ABSTAIN)
        result = report(records, ["q"], candidate="preference")
        self.assertFalse(result["answerable_contrasts"]["test/native/preference"]["observed_nonregression"])
        self.assertEqual(result["evidence_vs_empty"]["test/native/preference"]["conditional_f1_delta"], 0)

    def test_target_or_prompt_drift_and_missing_cases_reject(self):
        for field, value in (("family", "other"), ("target_unanswerable", True)):
            data = rows()
            data[-1][field] = value
            with self.assertRaises(ValueError):
                report(data, ["q"], candidate="preference")
        data = rows()
        data[2]["receipt"]["input_ids_digest"] = "changed"
        with self.assertRaises(ValueError):
            report(data, ["q"], candidate="preference")
        with self.assertRaises(ValueError):
            report(rows()[:-1], ["q"], candidate="preference")
        with self.assertRaises(ValueError):
            report(rows(), ["q"], candidate="invented")

    def test_failure_widens_uncertainty_and_invalidates_observed_nonregression(self):
        data = copy.deepcopy(rows())
        data[2].update(status="failed", f1=None)
        result = report(data, ["q"], candidate="preference")
        delta = result["answerable_contrasts"]["test/native/preference"]
        self.assertEqual(delta["family_delta_bounds"], [-1.0, 1.0])
        self.assertFalse(delta["observed_nonregression"])
        self.assertEqual(result["evidence_vs_empty"]["test/native/preference"]["missing_pairs"], 1)


if __name__ == "__main__":
    unittest.main()
