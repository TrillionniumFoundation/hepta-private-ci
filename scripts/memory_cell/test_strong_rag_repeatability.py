"""Explicit same-evidence/control invariance tests without model substitution."""

from copy import deepcopy
import unittest

from strong_rag_repeatability import audit_repeats


def arm(name, *, answer="site_11111111", success=True, selected=None):
    selected = ["source_1"] if selected is None else selected
    return dict(
        question_id="q1",
        arm=name,
        kind="correction",
        candidate_digest="pool_sha",
        selected=selected,
        status="succeeded",
        answer=answer,
        strict_task_success=success,
        required_sources_covered=True,
        receipt=dict(
            reader_identity="reader_sha",
            reader_profile="prompt_sha",
            token_limit=2048,
            input_tokens=115,
            input_ids_digest="input_sha",
            delivered_evidence=[dict(label="E1", excerpt="original")],
            generated_ids_digest="tokens_sha",
        ),
    )


class IdenticalEvidenceTests(unittest.TestCase):
    def test_equivalent_arms_match_and_report_without_claiming_superiority(self):
        rows = [arm("organized"), arm("program_support")]
        out = audit_repeats(rows, ["q1"], ("organized", "program_support"))
        self.assertEqual(out["observed_identical_prompt_pairs"], 1)
        self.assertTrue(out["deterministic_repeatability_established"])
        self.assertFalse(out["production_accepted"])

    def test_identical_prompt_answer_drift_is_observed_not_a_memory_gain(self):
        rows = [
            arm("organized"),
            arm("program_support", answer="site_22222222", success=False),
        ]
        out = audit_repeats(rows, ["q1"], ("organized", "program_support"))
        self.assertEqual(len(out["answer_disagreements"]), 1)
        self.assertEqual(len(out["task_result_disagreements"]), 1)
        self.assertFalse(out["deterministic_repeatability_established"])

    def test_identical_evidence_changed_prompt_or_reader_rejects(self):
        for field in (
            "reader_identity",
            "reader_profile",
            "input_ids_digest",
            "input_tokens",
            "delivered_evidence",
        ):
            rows = [arm("organized"), arm("program_support")]
            rows[1]["receipt"][field] = "changed"
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_repeats(rows, ["q1"], ("organized", "program_support"))

    def test_generated_ids_divergence_cannot_be_hidden_by_equal_decoded_text(self):
        rows = [arm("organized"), arm("program_support")]
        rows[1]["receipt"]["generated_ids_digest"] = "different_output_tokens"
        out = audit_repeats(rows, ["q1"], ("organized", "program_support"))
        self.assertEqual(len(out["output_token_disagreements"]), 1)
        self.assertFalse(out["deterministic_repeatability_established"])

    def test_incomplete_generation_remains_in_denominator(self):
        rows = [arm("organized"), arm("program_support")]
        rows[1] = dict(
            question_id="q1",
            arm="program_support",
            kind="correction",
            candidate_digest="pool_sha",
            selected=["source_1"],
            status="failed",
        )
        out = audit_repeats(rows, ["q1"], ("organized", "program_support"))
        self.assertEqual(out["unavailable_pairs"], 1)
        self.assertEqual(out["identical_ordered_evidence_pairs"], 1)
        self.assertFalse(out["deterministic_repeatability_established"])

    def test_different_order_is_not_silently_treated_as_same_prompt(self):
        rows = [
            arm("organized", selected=["source_1", "source_2"]),
            arm("program_support", selected=["source_2", "source_1"]),
        ]
        out = audit_repeats(rows, ["q1"], ("organized", "program_support"))
        self.assertEqual(out["identical_ordered_evidence_pairs"], 0)
        self.assertFalse(out["deterministic_repeatability_established"])

    def test_missing_duplicate_and_changed_gold_coverage_reject(self):
        rows = [arm("organized"), arm("program_support")]
        for modified in (rows[:-1], rows + rows[:1]):
            with self.assertRaises(ValueError):
                audit_repeats(modified, ["q1"], ("organized", "program_support"))
        changed = deepcopy(rows)
        changed[1]["required_sources_covered"] = False
        with self.assertRaises(ValueError):
            audit_repeats(changed, ["q1"], ("organized", "program_support"))


if __name__ == "__main__":
    unittest.main()
