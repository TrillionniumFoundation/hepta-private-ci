import copy
import unittest

from balanced_reader_trial import ARMS, report
from selector_answering import ABSTAIN


def rows():
    result = []
    for index, null in enumerate((False, True)):
        for arm in ARMS:
            empty = arm.startswith("empty_")
            balanced = arm.endswith("balanced")
            result.append(
                dict(
                    question_id=f"q{index}",
                    family=f"f{index}",
                    phase="test",
                    arm=arm,
                    status="succeeded",
                    pool_digest="pool",
                    selected=None if empty else 0,
                    answer=ABSTAIN if balanced else "answer",
                    f1=float(null) if balanced else 0.25,
                    target_unanswerable=null,
                    receipt=dict(
                        base_identity="base",
                        prompt_profile="prompt",
                        input_ids_digest="empty" if empty else "evidence",
                        delivered_evidence=[] if empty else [dict(excerpt="source")],
                    ),
                )
            )
    return result


class BalancedReportTests(unittest.TestCase):
    def test_abstention_gain_cannot_hide_answerable_regression(self):
        result = report(rows(), ["q0", "q1"])
        contrast = result["answerable_contrasts"]["test/native/balanced"]
        self.assertFalse(contrast["observed_nonregression"])
        self.assertFalse(contrast["significance_established"])
        self.assertFalse(result["production_accepted"])
        self.assertIsNone(
            result["summaries"]["test/native_balanced"]["semantic_citation_precision"]
        )

    def test_incomplete_duplicate_or_changed_generation_profile_is_not_a_comparison(
        self,
    ):
        original = rows()
        for data in (original[:-1], original + original[:1]):
            with self.assertRaises(ValueError):
                report(data, ["q0", "q1"])
        for key, value in (
            ("base_identity", "other"),
            ("prompt_profile", "other"),
            ("input_ids_digest", "other"),
            ("delivered_evidence", []),
        ):
            data = copy.deepcopy(original)
            data[1]["receipt"][key] = value
            with self.assertRaises(ValueError):
                report(data, ["q0", "q1"])

    def test_failure_stays_in_pair_interval_and_trial_denominator(self):
        data = rows()
        data[2].update(status="failed", f1=None)
        result = report(data, ["q0", "q1"])
        item = result["summaries"]["test/native_balanced"]
        self.assertEqual(
            (item["planned"], item["succeeded"], item["failed"]), (2, 1, 1)
        )
        self.assertEqual(
            result["answerable_contrasts"]["test/native/balanced"][
                "family_delta_bounds"
            ],
            [-1.0, 1.0],
        )
        data[2]["f1"] = 1
        with self.assertRaises(ValueError):
            report(data, ["q0", "q1"])

    def test_nonfinite_boolean_scores_or_renamed_family_reject(self):
        original = rows()
        for value in (float("nan"), float("inf"), True, -0.1, 1.1):
            data = copy.deepcopy(original)
            data[0]["f1"] = value
            with self.assertRaises(ValueError):
                report(data, ["q0", "q1"])
        data = rows()
        data[0]["family"] = "different"
        with self.assertRaises(ValueError):
            report(data, ["q0", "q1"])


if __name__ == "__main__":
    unittest.main()
