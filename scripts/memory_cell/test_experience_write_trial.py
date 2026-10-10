"""Pairing and missing-data tests; no pretrained result is asserted here."""

import copy
import unittest

from experience_write_trial import ARMS, summarize


def records():
    rows = []
    for q in ("q1", "q2"):
        for arm, (condition, mode) in ARMS.items():
            selection = [] if condition == "empty" else [condition]
            rows.append(dict(
                question_id=q, arm=arm, kind="fixture", status="succeeded",
                candidate_digest="fixed", selected=selection, answer="site_12345678",
                strict_task_success=arm != "empty",
                receipt=dict(reader_identity="base", reader_profile="same-prompt",
                             input_ids_digest=condition, delivered_evidence=selection,
                             input_tokens=10, generated_tokens=3, seconds=0.1,
                             knowledge_module_enabled=mode == "memory"),
            ))
    return rows


class WriteTrialTests(unittest.TestCase):
    def test_same_reader_same_evidence_comparison_and_costs(self):
        report = summarize(records(), ["q1", "q2"])
        self.assertEqual(report["all_attempts"], 10)
        self.assertEqual(report["knowledge_minus_organized"], 0)
        self.assertEqual(report["arms"]["knowledge"]["input_tokens"], 20)
        self.assertFalse(report["production_accepted"])
        self.assertIsNone(report["arms"]["parameter_only"]["semantic_citation_precision"])

    def test_no_missing_duplicate_or_resized_test_census(self):
        rows = records()
        for bad in (rows[:-1], rows + rows[:1], [rows[1]] + rows[1:]):
            with self.assertRaises(ValueError):
                summarize(bad, ["q1", "q2"])

    def test_parameter_effect_cannot_change_source_prompt_or_model(self):
        for field in ("input_ids_digest", "delivered_evidence", "reader_identity",
                      "reader_profile"):
            rows = records()
            next(r for r in rows if r["arm"] == "knowledge")["receipt"][field] = "drift"
            with self.assertRaises(ValueError):
                summarize(rows, ["q1", "q2"])

    def test_failed_attempt_remains_in_denominator(self):
        rows = records()
        failed = next(r for r in rows if r["arm"] == "knowledge")
        failed["status"] = "failed"
        failed.pop("receipt")
        failed.pop("strict_task_success")
        report = summarize(rows, ["q1", "q2"])
        self.assertEqual(report["arms"]["knowledge"]["planned"], 2)
        self.assertEqual(report["arms"]["knowledge"]["failed"], 1)
        self.assertEqual(report["knowledge_minus_organized"], -0.5)

    def test_unscored_success_and_candidate_mutation_reject(self):
        for value in (None, 1, "true"):
            rows = records()
            rows[0]["strict_task_success"] = value
            with self.assertRaises(ValueError):
                summarize(rows, ["q1", "q2"])
        rows = copy.deepcopy(records())
        rows[0]["candidate_digest"] = "changed"
        with self.assertRaises(ValueError):
            summarize(rows, ["q1", "q2"])


if __name__ == "__main__":
    unittest.main()
