"""Mechanism fixtures only; actual reader execution is a separate workflow step."""

import copy
import unittest
from unittest.mock import patch

from policy_read_audit import ALL_ARMS, audit_policy, extend_controls


def records():
    result = []
    for q in ("q1", "q2"):
        for arm in ALL_ARMS:
            result.append(
                dict(
                    question_id=q,
                    arm=arm,
                    kind="new_fact",
                    candidate_digest="pool",
                    status="succeeded",
                    answer="site_a",
                    selected=["source"],
                    strict_task_success=True,
                    required_sources_covered=True,
                    selection_receipt=dict(seconds=0.01),
                    receipt=dict(
                        reader_identity="reader",
                        reader_profile="prompt",
                        token_limit=2048,
                        input_tokens=32,
                        generated_tokens=8,
                        seconds=1.0,
                    ),
                )
            )
    return result


class PolicyReadAuditTests(unittest.TestCase):
    def test_identical_actual_results_are_not_learning_gain(self):
        report = audit_policy(records(), ("q1", "q2"), dict(write_seconds=4.0))
        for item in report["contrasts"].values():
            self.assertEqual((item["wins"], item["losses"], item["ties"]), (0, 0, 2))
            self.assertFalse(item["positive_complete_point_difference"])
        self.assertEqual(report["amortized_policy_write_seconds"]["100"], 0.04)
        self.assertIsNone(report["total_lifecycle_cost"])
        self.assertFalse(report["production_accepted"])

    def test_winning_weak_initialization_is_not_beating_organized_control(self):
        rows = records()
        for r in rows:
            if r["arm"] == "policy_initial":
                r["strict_task_success"] = False
        report = audit_policy(rows, ("q1", "q2"), dict(write_seconds=1))
        self.assertEqual(report["contrasts"]["policy_initial"]["wins"], 2)
        self.assertEqual(report["contrasts"]["organized"]["wins"], 0)
        self.assertFalse(report["significance_established"])

    def test_more_support_without_task_success_is_not_answer_gain(self):
        rows = records()
        for r in rows:
            r["strict_task_success"] = False
            if r["arm"] == "policy_initial":
                r["required_sources_covered"] = False
        item = audit_policy(rows, ("q1", "q2"), dict(write_seconds=1))["contrasts"][
            "policy_initial"
        ]
        self.assertEqual(item["support_gain_without_task_gain"], 2)
        self.assertEqual(item["all_planned_success_delta"], 0)

    def test_complete_census_and_matched_model_cannot_drift(self):
        for mutate in (
            lambda r: r.pop(),
            lambda r: r.append(copy.deepcopy(r[0])),
            lambda r: r[0].update(kind="correction"),
            lambda r: r[0].update(candidate_digest="another"),
            lambda r: r[0]["receipt"].update(reader_profile="other"),
            lambda r: r[0].update(answer=""),
            lambda r: r[0].update(strict_task_success=1),
            lambda r: r[0]["receipt"].update(seconds=float("nan")),
            lambda r: r[0]["receipt"].update(input_tokens=True),
        ):
            rows = records()
            mutate(rows)
            with self.assertRaises(ValueError):
                audit_policy(rows, ("q1", "q2"), dict(write_seconds=1))

    def test_failed_generation_stays_in_every_denominator(self):
        rows = records()
        for r in rows:
            if r["arm"] == "policy" and r["question_id"] == "q1":
                r["status"] = "failed"
                del r["strict_task_success"]
        report = audit_policy(rows, ("q1", "q2"), dict(write_seconds=1))
        self.assertEqual(report["arms"]["policy"]["planned"], 2)
        self.assertEqual(report["arms"]["policy"]["failed"], 1)
        self.assertEqual(report["contrasts"]["hybrid"]["failed_pairs"], 1)
        self.assertFalse(
            report["contrasts"]["hybrid"]["positive_complete_point_difference"]
        )

    def test_procedure_success_requires_actual_worker_receipt(self):
        rows = records()
        for r in rows:
            r["kind"] = "procedure"
            r["procedure_verification"] = dict(exit_code=0, seconds=0.2)
        good = audit_policy(rows, ("q1", "q2"), dict(write_seconds=1))
        self.assertEqual(good["arms"]["policy"]["procedure_seconds"], 0.4)
        rows[0]["procedure_verification"]["exit_code"] = 1
        with self.assertRaises(ValueError):
            audit_policy(rows, ("q1", "q2"), dict(write_seconds=1))

    def test_invalid_write_cost_is_not_silently_free(self):
        for value in (None, True, -1, float("inf")):
            with self.assertRaises(ValueError):
                audit_policy(records(), ("q1", "q2"), dict(write_seconds=value))

    def test_policy_admission_runs_before_any_selection(self):
        with patch(
            "policy_read_audit.validate_policy", side_effect=ValueError("withdrawn")
        ):
            with patch("policy_read_audit.choose") as choose:
                with self.assertRaisesRegex(ValueError, "withdrawn"):
                    extend_controls(
                        dict(cases=[]), {}, {}, reader_identity="r", revoked={"root"}
                    )
                choose.assert_not_called()


if __name__ == "__main__":
    unittest.main()
