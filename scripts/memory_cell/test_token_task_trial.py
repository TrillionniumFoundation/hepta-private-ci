import copy
import unittest

from token_task_trial import ARMS, report_records


class FactorialReportTests(unittest.TestCase):
    def rows(self):
        rows = []
        for arm in ARMS:
            empty = arm.startswith("empty")
            rows.append(dict(
                question_id="q", family="family", phase="test", arm=arm,
                selected=None if empty else 0, pool_digest="pool", input_digest="features",
                candidate_ids=["w"], status="succeeded", answer="Kyoto [E1]",
                f1=1.0, exact_match=1.0, reference_covered=not empty,
                receipt=dict(base_identity="base", prompt_profile="template",
                    input_ids_digest="empty" if empty else "same-prompt",
                    delivered_evidence=[] if empty else [{"label": "E1"}]),
            ))
        return rows

    def test_reader_and_ranking_contrasts_are_not_combined(self):
        report = report_records(self.rows(), ["q"])
        self.assertEqual(len(report["contrasts"]), 4)
        self.assertFalse(report["contrasts"]["test/native_base->token_base"]["reader_changed"])
        self.assertTrue(report["contrasts"]["test/native_base->native_task"]["reader_changed"])
        self.assertFalse(report["production_accepted"])
        self.assertEqual(report["summaries"]["test/empty_task"]["invalid_citation_markers"], 1)

    def test_missing_duplicate_and_prompt_drift_reject(self):
        rows = self.rows()
        for modified in (rows[:-1], rows + [rows[0]]):
            with self.assertRaises(ValueError):
                report_records(modified, ["q"])
        for field in ("input_ids_digest", "prompt_profile", "base_identity"):
            modified = copy.deepcopy(rows)
            modified[2]["receipt"][field] = "changed"
            with self.assertRaises(ValueError):
                report_records(modified, ["q"])

    def test_failed_attempt_is_not_removed_from_denominator(self):
        rows = self.rows()
        rows[1].update(status="failed", f1=None, exact_match=None)
        report = report_records(rows, ["q"])
        self.assertEqual(report["summaries"]["test/token_base"]["failed"], 1)
        self.assertEqual(report["contrasts"]["test/native_base->token_base"]["missing_pairs"], 1)
        self.assertEqual(report["contrasts"]["test/native_base->token_base"]["conservative_95_interval"], [-1, 1])


if __name__ == "__main__":
    unittest.main()
