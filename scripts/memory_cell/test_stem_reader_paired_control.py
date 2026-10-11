"""Paired Reader diagnostics retain every failed or unscorable question."""

import unittest

from stem_reader_paired_control import compare_frozen_to_no_evidence


PHASES = ("select", "retention", "test", "transfer")


def fixtures():
    original, without, targets = [], [], {}
    for phase in PHASES:
        for n in range(8):
            q = f"{phase}-{n}"
            family = f"family-{phase}-{n}"
            targets[q] = "SUPPORTED"
            original.append(dict(
                stage=48, phase=phase, arm="frozen_rerank",
                question_id=q, family=family,
                status="succeeded", answer="SUPPORTED",
                receipt={"delivered_evidence": [{"label": "E1"}]},
            ))
            without.append(dict(
                phase=phase, question_id=q, family=family,
                status="succeeded", answer="UNKNOWN",
                evidence_count=0, receipt={"delivered_evidence": []},
            ))
    return original, without, targets


def diagnose(answer, target):
    return 1.0 if answer == target else 0.0


class ReaderPairedTests(unittest.TestCase):
    def test_complete_32_question_counterfactual(self):
        original, empty, targets = fixtures()
        out = compare_frozen_to_no_evidence(original, empty, targets, diagnose)
        self.assertEqual(out["matched_pairs"], 32)
        self.assertEqual(out["per_phase"]["test"]["paired_diagnostic_delta_mean"], 1)
        self.assertEqual(out["per_phase"]["test"]["all_planned_answer_delta_bounds"], [1, 1])
        self.assertFalse(out["qualified_evidence_sufficiency"])
        self.assertFalse(out["production_accepted"])

    def test_missing_read_failure_stays_in_uncertainty_bounds(self):
        original, empty, targets = fixtures()
        original[0].update(status="failed")
        original[0].pop("answer")
        original[0].pop("receipt")
        result = compare_frozen_to_no_evidence(original, empty, targets, diagnose)
        phase = result["per_phase"]["select"]
        self.assertEqual(phase["frozen_reader_succeeded"], 7)
        self.assertEqual(phase["both_answered_and_scored"], 7)
        self.assertEqual(phase["omitted_or_failed_pairs"], 1)
        self.assertEqual(phase["all_planned_answer_delta_bounds"], [0.75, 1.0])

    def test_unscorable_target_does_not_become_a_perfect_answer(self):
        original, empty, targets = fixtures()
        result = compare_frozen_to_no_evidence(
            original, empty, targets,
            lambda answer, target: None,
        )
        self.assertIsNone(result["per_phase"]["transfer"]["paired_diagnostic_delta_mean"])
        self.assertEqual(result["per_phase"]["transfer"]["all_planned_answer_delta_bounds"],
                         [-1.0, 1.0])

    def test_missing_extra_duplicate_and_cross_family_pair_reject(self):
        original, empty, targets = fixtures()
        for altered in (empty[:-1], empty[:-1] + [empty[0]]):
            with self.assertRaises(ValueError):
                compare_frozen_to_no_evidence(
                    original, altered, targets, diagnose,
                )
        original[0]["family"] = "other-family"
        with self.assertRaisesRegex(ValueError, "misbound"):
            compare_frozen_to_no_evidence(original, empty, targets, diagnose)

    def test_unbound_zero_evidence_source_is_hard_failure(self):
        original, empty, targets = fixtures()
        empty[0]["receipt"]["delivered_evidence"] = [{"label": "E1"}]
        with self.assertRaisesRegex(ValueError, "received a source"):
            compare_frozen_to_no_evidence(
                original, empty, targets, diagnose,
            )


if __name__ == "__main__":
    unittest.main()
