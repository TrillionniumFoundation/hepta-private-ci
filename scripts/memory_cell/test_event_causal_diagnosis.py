"""Test real-answer attribution semantics without inventing model results."""

from copy import deepcopy
import unittest

from event_causal_diagnosis import ARMS, diagnose


def case(qid, *, kind="new_fact", correct=(), covered=(), fail=()):
    rows = []
    for arm in ARMS:
        row = dict(
            question_id=qid,
            kind=kind,
            arm=arm,
            status="failed" if arm in fail else "succeeded",
            candidate_digest="frozen-candidates-" + qid,
        )
        if arm not in fail:
            row.update(
                strict_task_success=arm in correct,
                required_sources_covered=arm in covered,
                receipt=dict(
                    reader_identity="frozen-weights",
                    reader_profile="frozen-prompt",
                    token_limit=2048,
                ),
            )
        rows.append(row)
    return rows


class PairedAttributionTests(unittest.TestCase):
    def test_distinguishes_reader_retrieval_organization_and_empty_leakage(self):
        rows = (
            case(
                "new",
                correct=("organized", "program_support"),
                covered=("organized", "program_support"),
            )
            + case("reader", kind="correction", covered=("program_support",))
            + case(
                "baseline",
                kind="composition",
                correct=("hybrid", "organized", "program_support"),
                covered=("hybrid", "organized", "program_support"),
            )
            + case(
                "guess",
                kind="procedure",
                correct=ARMS,
                covered=("hybrid", "organized", "program_support"),
            )
        )
        result = diagnose(rows, ("new", "reader", "baseline", "guess"))
        self.assertEqual(
            [c["category"] for c in result["cases"]],
            [
                "memory_organization_recovers_missing_support",
                "controlled_support_reader_or_task_failure",
                "strong_rag_already_succeeds",
                "no_evidence_control_already_succeeds",
            ],
        )
        self.assertEqual(
            result["paired_contrasts"]["organized_minus_hybrid"]["wins"], 1
        )
        self.assertEqual(result["by_task_kind"]["procedure"]["planned"], 1)
        self.assertFalse(result["program_support_is_human_verified"])
        self.assertEqual(
            result["ablation_dispositions"]["not_demonstrated_necessary"], 1
        )
        self.assertFalse(result["controlled_premise_necessity_proven"])
        self.assertFalse(result["policy_or_parametric_learning_qualified"])

    def test_missing_attempt_is_not_silently_assigned_zero(self):
        rows = case(
            "q",
            correct=("hybrid", "program_support"),
            covered=("hybrid", "program_support"),
            fail=("organized",),
        )
        result = diagnose(rows, ("q",))
        contrast = result["paired_contrasts"]["organized_minus_hybrid"]
        self.assertEqual(contrast["unobserved"], 1)
        self.assertEqual(
            (contrast["all_planned_delta_lower"], contrast["all_planned_delta_upper"]),
            (-1, 1),
        )
        self.assertIsNone(contrast["observed_pair_success_delta"])
        self.assertEqual(result["cases"][0]["category"], "incomplete_execution")

    def test_omission_success_does_not_show_necessary_evidence(self):
        rows = case("q", correct=("program_support", "without_prerequisite"))
        report = diagnose(rows, ("q",))
        self.assertEqual(report["cases"][0]["ablation"], "not_demonstrated_necessary")
        self.assertEqual(
            report["ablation_dispositions"]["not_demonstrated_necessary"], 1
        )

    def test_rejects_changed_candidates_reader_and_missing_or_duplicate_pairs(self):
        rows = case("q", correct=ARMS)
        for changed in (rows[:-1], rows + rows[:1]):
            with self.assertRaises(ValueError):
                diagnose(changed, ("q",))
        changed = deepcopy(rows)
        changed[0]["candidate_digest"] = "other"
        with self.assertRaises(ValueError):
            diagnose(changed, ("q",))
        changed = deepcopy(rows)
        changed[0]["receipt"]["reader_profile"] = "other"
        with self.assertRaises(ValueError):
            diagnose(changed, ("q",))
        changed = deepcopy(rows)
        changed[1]["strict_task_success"] = 1
        with self.assertRaises(ValueError):
            diagnose(changed, ("q",))


if __name__ == "__main__":
    unittest.main()
