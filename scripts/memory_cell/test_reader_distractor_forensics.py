"""Adversarial literal-source attribution tests; NO generated model fixtures."""

from pathlib import Path
import tempfile
import unittest

from reader_distractor_forensics import (
    audit,
    classify_loss,
    reversal_control,
    strict_identifier,
)


def case(answer, *, kind="new_fact"):
    parsed = strict_identifier(answer)
    return dict(
        kind=kind,
        status="succeeded",
        strict_task_success=False,
        answer=answer,
        parsed_identifier=parsed,
        receipt=dict(
            delivered_evidence=[
                dict(
                    original_id="event_target",
                    label="E1",
                    excerpt='{"entity":"service_1","attribute":"location",'
                    '"value":"site_00000001"}',
                ),
                dict(
                    original_id="event_distractor",
                    label="E2",
                    excerpt='{"entity":"component_other","attribute":"location",'
                    '"value":"site_00000002"}',
                ),
            ]
        ),
    )


GOLD = dict(
    id="case_1",
    expected="site_00000001",
    entity="service_1",
    kind="new_fact",
)


class OriginalReaderForensicsTests(unittest.TestCase):
    def test_wrong_value_is_bound_to_actual_other_entity_source(self):
        row = case("site_00000002 [E2]")
        finding = classify_loss(row, GOLD)
        self.assertEqual(finding["cause"], "wrong_literal_copied_from_other_entity")
        self.assertEqual(finding["emitted_literal"], "site_00000002")
        self.assertEqual(
            finding["matching_original_sources"],
            [
                dict(
                    source_id="event_distractor",
                    evidence_label="E2",
                    entity="component_other",
                    attribute="location",
                )
            ],
        )

    def test_correct_value_in_wrong_bracket_grammar_is_not_task_success(self):
        row = case("[site_00000001]")
        finding = classify_loss(row, GOLD)
        self.assertEqual(
            finding["cause"], "correct_literal_invalid_output_grammar"
        )
        self.assertIsNone(row["parsed_identifier"])

    def test_absent_source_match_is_not_invented(self):
        row = case("site_abcdef01 [E1]")
        finding = classify_loss(row, GOLD)
        self.assertEqual(
            finding["cause"], "other_observed_or_unresolved_failure"
        )
        self.assertEqual(finding["matching_original_sources"], [])

    def test_other_entity_does_not_imply_human_semantic_review(self):
        row = case("site_00000002")
        finding = classify_loss(row, GOLD)
        self.assertNotIn("semantic_correctness", finding)
        self.assertNotIn("human_reviewed", finding)

    def test_strict_parser_rejects_grammar_and_answer_injection(self):
        self.assertIsNone(strict_identifier("answer: site_00000001"))
        self.assertIsNone(strict_identifier("[site_00000001]"))
        self.assertEqual(
            strict_identifier("site_00000001 [E1]"),
            "site_00000001",
        )

    def test_never_classify_success_or_executed_program_as_failing(self):
        row = case("site_00000002")
        row["strict_task_success"] = True
        with self.assertRaisesRegex(ValueError, "failed nonprogram"):
            classify_loss(row, GOLD)
        row["strict_task_success"] = False
        row["kind"] = "procedure"
        with self.assertRaisesRegex(ValueError, "failed nonprogram"):
            classify_loss(row, GOLD)

    def test_original_graded_answer_field_is_not_reinterpreted(self):
        row = case("site_00000002")
        row["parsed_identifier"] = "site_00000001"
        with self.assertRaisesRegex(ValueError, "grammar audit drift"):
            classify_loss(row, GOLD)

    def test_missing_external_original_archives_never_become_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.zip"
            model = Path(directory) / "model.zip"
            source.write_bytes(b"not-a-zip")
            model.write_bytes(b"not-a-zip")
            with self.assertRaises(ValueError):
                audit(source, model)


    def test_order_reversal_pair_is_not_a_new_model_call(self):
        pair = self._reversal_pair()
        report = reversal_control({"one": pair})
        self.assertEqual(report["paired_tasks"], 1)
        self.assertEqual(report["same_success_status"], 1)
        self.assertEqual(report["same_parsed_literal"], 1)
        self.assertFalse(report["semantic_review"])

    def test_reversal_requires_exact_four_evidence_ids_and_equal_token_budget(self):
        for mutation in ("selected", "input_tokens", "reader_identity"):
            with self.subTest(mutation=mutation):
                pair = self._reversal_pair()
                if mutation == "selected":
                    pair["hybrid_k4_reversed"]["selected"].reverse()
                elif mutation == "input_tokens":
                    pair["hybrid_k4_reversed"]["receipt"]["input_tokens"] += 1
                else:
                    pair["hybrid_k4_reversed"]["receipt"]["reader_identity"] = "changed"
                with self.assertRaises(ValueError):
                    reversal_control({"one": pair})

    def test_failed_or_unauthorized_reversal_cannot_claim_reader_gain(self):
        for mutation in ("direct_failed", "reverse_failed", "semantic_claim"):
            with self.subTest(mutation=mutation):
                pair = self._reversal_pair()
                if mutation == "direct_failed":
                    pair["hybrid_k4"]["status"] = "failed"
                elif mutation == "reverse_failed":
                    pair["hybrid_k4_reversed"]["status"] = "failed"
                else:
                    pair["hybrid_k4_reversed"]["receipt"][
                        "independent_semantic_review"
                    ] = True
                with self.assertRaises(ValueError):
                    reversal_control({"one": pair})

    @staticmethod
    def _reversal_pair():
        def row(arm, ids):
            return dict(
                question_id="one",
                arm=arm,
                kind="new_fact",
                candidate_digest="fixed",
                status="succeeded",
                selected=ids,
                strict_task_success=False,
                answer="site_00000002 [E1]",
                parsed_identifier="site_00000002",
                receipt=dict(
                    reader_identity="model",
                    reader_profile="profile",
                    token_limit=2048,
                    input_tokens=100,
                    trainable_parameters=0,
                    answer_postprocessed=False,
                    independent_semantic_review=False,
                ),
            )

        ids = ["e0", "e1", "e2", "e3"]
        return {
            "hybrid_k4": row("hybrid_k4", ids),
            "hybrid_k4_reversed": row(
                "hybrid_k4_reversed", list(reversed(ids))
            ),
        }


if __name__ == "__main__":
    unittest.main()
